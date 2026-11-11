"""FlashData protocol-2 live trials and explicit owner handoff, with no query retries."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ._auth_store import AuthStore
from .errors import AuthError

MANAGEMENT_ORIGIN = "https://api.flashdata.dev"
DATA_ORIGIN = "https://data.flashdata.dev"
SITE_ORIGIN = "https://flashdata.dev"
_BASE = MANAGEMENT_ORIGIN + "/v2/agent-connections"
_SCOPES = ["youtube_transcript", "youtube_metadata"]
_REGISTER = {
    "name": "YouTube Transcript API Toolkit",
    "audience": "coding",
    "scopes": _SCOPES,
    "client": "flashdata-transcript",
    "transport": "cli",
}


def _match(value: Any, pattern: str, description: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise AuthError(f"Invalid {description} in onboarding state/response. State was kept.")
    return value


def _connection(value: Any, expected: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthError("Onboarding did not return a connection.")
    identifier = _match(value.get("id"), r"acn_[A-Za-z0-9_-]{8,100}", "connection ID")
    if expected is not None and identifier != expected:
        raise AuthError("The returned connection does not match saved access.")
    if value.get("ownership") not in {"owned", "unowned"}:
        raise AuthError("Unknown connection ownership.")
    if value.get("lifecycle") != "valid" or value.get("access") != "ready":
        raise AuthError(
            "Saved access is blocked or revoked. Use an owner key; no new trial was created."
        )
    scopes = value.get("scopes")
    if not isinstance(scopes, list) or any(scope not in _SCOPES for scope in scopes):
        raise AuthError("The connection permissions do not match this toolkit.")
    generation = value.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise AuthError("Invalid credential generation.")
    return value


def _expired(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed <= datetime.now(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AuthError("Invalid expiry in onboarding state/response.") from exc


def _saved(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("phase") not in {"trial", "owned", "handoff_pending"}:
        raise AuthError("Trial setup is incomplete. Run 'flashdata-transcript auth trial' again.")
    connection = _connection(state.get("connection"))
    expected = "unowned" if state["phase"] == "trial" else "owned"
    if connection["ownership"] != expected:
        raise AuthError("Saved ownership does not match the authentication phase. State was kept.")
    if not isinstance(state.get("credentials"), dict):
        raise AuthError("Saved credentials are missing. State was not reset.")
    return state


def _key(state: dict[str, Any]) -> str:
    return _match(state["credentials"].get("apiKey"), r"fd_[A-Za-z0-9_-]{16,240}", "API key")


def resolve_api_key(api_key: str | None = None, state_dir: str | Path | None = None) -> str:
    """Explicit key > environment > saved access. Never registers or refreshes a trial."""
    if api_key is not None:
        return api_key
    if "FLASHDATA_API_KEY" in os.environ:
        key = os.environ["FLASHDATA_API_KEY"].strip()
        if not key:
            raise AuthError("FLASHDATA_API_KEY is empty. Set it or unset it to use saved access.")
        return key
    state = AuthStore(state_dir).read()
    if state is None:
        raise AuthError("Run 'flashdata-transcript auth trial' or set FLASHDATA_API_KEY first.")
    _saved(state)
    if state["phase"] == "handoff_pending":
        raise AuthError("Finish account connection with 'flashdata-transcript auth finish'.")
    if state["connection"]["ownership"] == "unowned" and _expired(
        state["connection"].get("trialExpiresAt")
    ):
        raise AuthError("Your saved trial expired. Set an owner API key; no new trial was created.")
    return _key(state)


def _verify_fresh_process(store: AuthStore, connection: dict[str, Any]) -> None:
    command = [
        sys.executable,
        "-m",
        "flashdata_transcript._verify_auth",
        str(store.directory),
        connection["id"],
        str(connection["generation"]),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthError(
            "Saved owner access could not be verified. Run 'auth finish' again."
        ) from exc
    if result.returncode != 0 or result.stdout.strip() != "verified":
        raise AuthError(
            "Saved owner access was not verified. State was kept; run 'auth finish' again."
        )


class AuthManager:
    """Explicit trial setup and browser claim lifecycle. Returned summaries never contain keys."""

    def __init__(
        self,
        state_dir: str | Path | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        verifier: Callable[[AuthStore, dict[str, Any]], None] | None = None,
        registration_transport: str = "cli",
    ) -> None:
        if registration_transport not in {"cli", "api"}:
            raise ValueError("Registration transport must be cli or api.")
        self.store = AuthStore(state_dir)
        self._registration_body = {**_REGISTER, "transport": registration_transport}
        self._http = httpx.Client(timeout=30, transport=transport, follow_redirects=False)
        self._verifier = verifier or _verify_fresh_process

    def __enter__(self) -> AuthManager:
        return self

    def __exit__(self, *_args: Any) -> None:
        self._http.close()

    def _request(
        self, method: str, path: str, token: str | None = None, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "flashdata-transcript/0.2.0"}
        if token is not None:
            _match(token, r"[A-Za-z0-9_-]{1,256}", "credential")
            headers["Authorization"] = f"Bearer {token}"
        try:
            with self._http.stream(
                method, _BASE + path, json=body, headers=headers, follow_redirects=False
            ) as response:
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 128 * 1024:
                        raise AuthError(
                            "Onboarding response exceeded its size limit. State was kept."
                        )
                if not 200 <= response.status_code < 300:
                    raise AuthError(
                        f"FlashData onboarding returned HTTP {response.status_code}. "
                        "Saved access was kept. Check 'auth status' or use an existing owner key."
                    )
                data = json.loads(content)
        except httpx.HTTPError as exc:
            raise AuthError(
                "Onboarding response unavailable. Repeat the same auth command to recover saved "
                "state; do not remove the state directory."
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise AuthError("Onboarding returned invalid JSON. Saved state was kept.") from exc
        if not isinstance(data, dict):
            raise AuthError("Onboarding returned an invalid response. Saved state was kept.")
        return data

    def _summary(self, connection: dict[str, Any], phase: str) -> dict[str, Any]:
        return {
            "source": "saved",
            "status": phase,
            "connection_id": connection["id"],
            "ownership": connection["ownership"],
            "scopes": connection["scopes"],
            "trial_expires_at": connection.get("trialExpiresAt") if phase == "trial" else None,
            "trial_credits": connection.get("trialCredits") if phase == "trial" else None,
            "trial_request_counts": connection.get("trialRequestCounts")
            if phase == "trial"
            else None,
            "credential_protection": self.store.protection,
            "state_directory": str(self.store.directory),
        }

    def _identity(self, state: dict[str, Any]) -> dict[str, Any]:
        connection = state["connection"]
        result = self._request("GET", f"/{connection['id']}/identity", _key(state))
        result = _connection(result.get("connection"), connection["id"])
        if result["generation"] != connection["generation"]:
            raise AuthError("Credential generation changed. Run 'auth finish' to recover.")
        return result

    def trial(self) -> dict[str, Any]:
        if "FLASHDATA_API_KEY" in os.environ:
            resolve_api_key()
            return {"source": "environment", "status": "configured", "trial_created": False}
        with self.store.locked():
            state = self.store.read()
            if state is not None and state.get("phase") != "registering":
                _saved(state)
                if state["phase"] == "handoff_pending":
                    raise AuthError(
                        "Account handoff is pending. Run 'auth finish'; no trial was created."
                    )
                connection = self._identity(state)
                return self._summary(connection, state["phase"])
            capabilities = self._request("GET", "/capabilities")
            if (
                capabilities.get("protocolVersion") != 2
                or capabilities.get("available") is not True
                or capabilities.get("dataOrigin") != DATA_ORIGIN
            ):
                raise AuthError(
                    "Live trial onboarding is unavailable. Use an existing FlashData API key."
                )
            trial = capabilities.get("trial")
            if (
                not isinstance(trial, dict)
                or not isinstance(trial.get("scopes"), list)
                or not set(_SCOPES).issubset(trial["scopes"])
            ):
                raise AuthError("The live trial does not currently support the required sources.")
            if state is None:
                state = {
                    "version": 1,
                    "phase": "registering",
                    "registration": {
                        "proof": secrets.token_urlsafe(32),
                        "body": self._registration_body,
                    },
                }
                self.store.save(state)  # Persist the idempotency proof before sending anything.
            registration = state.get("registration", {})
            if not isinstance(registration, dict):
                raise AuthError("Saved registration cannot be read. State was not reset.")
            proof = _match(registration.get("proof"), r"[A-Za-z0-9_-]{43}", "registration proof")
            body = registration.get("body")
            if (
                not isinstance(body, dict)
                or body.get("transport") not in {"cli", "api"}
                or {**body, "transport": "cli"} != _REGISTER
            ):
                raise AuthError(
                    "Saved registration differs from this toolkit. State was not reset."
                )
            result = self._request("POST", "/registrations", proof, registration["body"])
            if result.get("dataOrigin") != DATA_ORIGIN:
                raise AuthError("Unexpected Data API origin. No query was sent.")
            connection = _connection(result.get("connection"))
            if connection["ownership"] != "unowned" or set(connection["scopes"]) != set(_SCOPES):
                raise AuthError("Registration did not grant the requested trial scopes.")
            if _expired(connection.get("trialExpiresAt")):
                raise AuthError("The returned trial has expired. No new trial was created.")
            credentials = result.get("credentials", {})
            if (
                not isinstance(credentials, dict)
                or credentials.get("connectionId") != connection["id"]
            ):
                raise AuthError("Registration credentials do not match the connection.")
            if credentials.get("generation") != connection["generation"]:
                raise AuthError("Registration credential generation does not match.")
            for field, prefix in [
                ("setupCredential", "fda_setup_"),
                ("handoffProof", "fda_handoff_"),
            ]:
                _match(credentials.get(field), prefix + r"[A-Za-z0-9_-]{43}", field)
            candidate = {
                **state,
                "phase": "trial",
                "connection": connection,
                "credentials": credentials,
            }
            _key(candidate)
            self.store.save(candidate)
            return self._summary(connection, "trial")

    def status(self) -> dict[str, Any]:
        if "FLASHDATA_API_KEY" in os.environ:
            resolve_api_key()
            return {"source": "environment", "status": "configured", "verified": False}
        with self.store.locked():
            state = self.store.read()
            if state is None:
                return {"source": "none", "status": "not_configured"}
            if state.get("phase") == "registering":
                return {"source": "saved", "status": "registering", "next_command": "auth trial"}
            _saved(state)
            return self._summary(self._identity(state), state["phase"])

    def claim(self) -> dict[str, Any]:
        with self.store.locked():
            state = self.store.read()
            if state is None:
                raise AuthError("There is no saved trial to claim. Run 'auth trial' first.")
            _saved(state)
            if state["phase"] != "trial":
                raise AuthError(
                    "Use 'auth finish' or your existing owner key; this trial is already claimed."
                )
            existing = state.get("claim")
            if isinstance(existing, dict) and not _expired(existing.get("expiresAt")):
                return self._claim_summary(existing)
            identifier = state["connection"]["id"]
            credential = state["credentials"].get("setupCredential")
            result = self._request("POST", f"/{identifier}/claims", credential, {})
            summary = self._claim_summary(result)
            if _expired(result.get("expiresAt")):
                raise AuthError("The claim link has expired. Run 'auth claim' again.")
            state["claim"] = result
            self.store.save(state)
            return summary

    @staticmethod
    def _claim_summary(claim: dict[str, Any]) -> dict[str, Any]:
        identifier = _match(claim.get("claimId"), r"acl_[A-Za-z0-9_-]{8,100}", "claim ID")
        path = f"/connect/claim/{identifier}"
        if claim.get("claimPath") != path:
            raise AuthError("Unexpected claim URL. No browser was opened.")
        code = _match(claim.get("confirmationCode"), r"[0-9]{8}", "confirmation code")
        return {
            "claim_url": SITE_ORIGIN + path,
            "confirmation_code": code,
            "expires_at": claim.get("expiresAt"),
            "next_command": "auth finish --wait",
        }

    def finish(self, *, wait: bool = False, timeout: float = 600) -> dict[str, Any]:
        if not 0 < timeout <= 3600:
            raise ValueError("Authentication wait timeout must be between 0 and 3600 seconds.")
        deadline = time.monotonic() + timeout
        with self.store.locked():
            while True:
                state = self.store.read()
                if state is None:
                    raise AuthError("There is no saved trial to finish.")
                _saved(state)
                if state["phase"] == "owned":
                    return self._summary(self._identity(state), "owned")
                connection = state["connection"]
                proof = _match(
                    state["credentials"].get("handoffProof"),
                    r"fda_handoff_[A-Za-z0-9_-]{43}",
                    "handoff proof",
                )
                path = f"/{connection['id']}"
                onboarding = self._request("GET", path + "/onboarding", proof)
                status = onboarding.get("status")
                if status in {"handoff_ready", "installed"}:
                    if status == "handoff_ready" and state["phase"] != "handoff_pending":
                        delivered = self._request("POST", path + "/handoff", proof, {})
                        owner = _connection(delivered.get("connection"), connection["id"])
                        credentials = delivered.get("credentials", {})
                        if (
                            owner["ownership"] != "owned"
                            or not isinstance(credentials, dict)
                            or credentials.get("connectionId") != owner["id"]
                            or credentials.get("generation") != owner["generation"]
                            or owner["generation"] <= connection["generation"]
                        ):
                            raise AuthError("Owner credentials did not match the expected handoff.")
                        state.update(phase="handoff_pending", connection=owner)
                        state["credentials"]["apiKey"] = credentials.get("apiKey")
                        state["credentials"]["generation"] = owner["generation"]
                        _key(state)
                        self.store.save(state)
                    if state["phase"] != "handoff_pending":
                        raise AuthError(
                            "Installed owner key is missing locally. Configure an owner API key."
                        )
                    self._verifier(self.store, state["connection"])
                    if status != "installed":
                        acknowledged = self._request(
                            "POST", path + "/handoff/ack", proof, {"apiKey": _key(state)}
                        )
                        if (
                            acknowledged.get("status") != "confirmed"
                            or acknowledged.get("generation") != state["connection"]["generation"]
                        ):
                            raise AuthError(
                                "Owner key acknowledgement is incomplete. Run 'auth finish' again."
                            )
                    owner = self._identity(state)
                    if owner["ownership"] != "owned" or owner.get("installed") is not True:
                        raise AuthError(
                            "Owner key installation is incomplete. Run 'auth finish' again."
                        )
                    state = {
                        "version": 1,
                        "phase": "owned",
                        "connection": owner,
                        "credentials": {"apiKey": _key(state)},
                    }
                    self.store.save(state)  # Remove obsolete registration/setup/handoff proofs.
                    return self._summary(owner, "owned")
                if status not in {"awaiting_claim", "claim_processing"}:
                    raise AuthError(
                        "Account connection expired or is blocked. Use an existing owner API key."
                    )
                remaining = deadline - time.monotonic()
                if not wait or remaining <= 0:
                    return {"status": status, "next_command": "auth finish --wait"}
                delay = onboarding.get("pollAfterSeconds", 5)
                if (
                    isinstance(delay, bool)
                    or not isinstance(delay, (int, float))
                    or not 1 <= delay <= 300
                ):
                    raise AuthError("Invalid onboarding polling interval.")
                if delay >= remaining:
                    return {"status": status, "next_command": "auth finish --wait"}
                time.sleep(delay)

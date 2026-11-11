import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from flashdata import FlashData

from flashdata_transcript import AuthError, TranscriptClient
from flashdata_transcript._auth_store import AuthStore
from flashdata_transcript.auth import DATA_ORIGIN, AuthManager, resolve_api_key
from flashdata_transcript.cli import main

TRIAL_KEY = "fd_" + "t" * 43
OWNER_KEY = "fd_" + "o" * 43
SETUP = "fda_setup_" + "s" * 43
HANDOFF = "fda_handoff_" + "h" * 43
CONNECTION = "acn_testconnection01"
CLAIM = "acl_testclaim0001"


def future(hours=72):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class Server:
    def __init__(self):
        self.calls = []
        self.lost_registration = False
        self.lost_ack = False
        self.approved = False
        self.installed = False
        self.identity_error = None
        self.poll_status = None
        self.available = True
        self.data_origin = DATA_ORIGIN

    def connection(self, owner=False):
        return {
            "id": CONNECTION,
            "name": "Test transcript client",
            "ownership": "owned" if owner else "unowned",
            "lifecycle": "valid",
            "access": "ready",
            "generation": 2 if owner else 1,
            "installed": self.installed if owner else False,
            "trialExpiresAt": future(),
            "trialCredits": 1,
            "scopes": ["youtube_metadata", "youtube_transcript"],
            "trialRequestCounts": None
            if owner
            else {"youtube_metadata": 100, "youtube_transcript": 100},
        }

    def handler(self, request):
        assert request.url.host == "api.flashdata.dev"
        assert request.url.scheme == "https"
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/v2/agent-connections")
        credential = request.headers.get("Authorization")
        self.calls.append((request.method, path, credential, body))
        if path == "/capabilities":
            return httpx.Response(
                200,
                json={
                    "protocolVersion": 2,
                    "available": self.available,
                    "dataOrigin": self.data_origin,
                    "trial": {"credits": 1, "scopes": ["youtube_transcript", "youtube_metadata"]},
                },
            )
        if path == "/registrations":
            assert len(credential.removeprefix("Bearer ")) == 43
            assert body["scopes"] == ["youtube_transcript", "youtube_metadata"]
            assert body["client"] == "flashdata-transcript"
            if self.lost_registration:
                self.lost_registration = False
                raise httpx.ReadTimeout("response lost", request=request)
            return httpx.Response(
                201,
                json={
                    "dataOrigin": self.data_origin,
                    "connection": self.connection(),
                    "credentials": {
                        "connectionId": CONNECTION,
                        "apiKey": TRIAL_KEY,
                        "generation": 1,
                        "setupCredential": SETUP,
                        "handoffProof": HANDOFF,
                    },
                },
            )
        if path == f"/{CONNECTION}/identity":
            if self.identity_error:
                return httpx.Response(self.identity_error, json={"detail": TRIAL_KEY})
            owner = credential == "Bearer " + OWNER_KEY
            assert owner or credential == "Bearer " + TRIAL_KEY
            if self.approved and not owner:
                return httpx.Response(403, json={"detail": "Old key revoked"})
            return httpx.Response(200, json={"connection": self.connection(owner)})
        if path == f"/{CONNECTION}/claims":
            assert credential == "Bearer " + SETUP
            return httpx.Response(
                201,
                json={
                    "claimId": CLAIM,
                    "claimPath": f"/connect/claim/{CLAIM}",
                    "confirmationCode": "12345678",
                    "expiresAt": future(0.25),
                    "pollAfterSeconds": 5,
                },
            )
        if path == f"/{CONNECTION}/onboarding":
            assert credential == "Bearer " + HANDOFF
            status = self.poll_status or (
                "installed"
                if self.installed
                else "handoff_ready"
                if self.approved
                else "awaiting_claim"
            )
            return httpx.Response(
                200,
                json={
                    "status": status,
                    "connection": self.connection(self.approved),
                    "pollAfterSeconds": 5,
                },
            )
        if path == f"/{CONNECTION}/handoff":
            assert self.approved and credential == "Bearer " + HANDOFF
            return httpx.Response(
                200,
                json={
                    "status": "delivered",
                    "connection": self.connection(True),
                    "credentials": {
                        "connectionId": CONNECTION,
                        "apiKey": OWNER_KEY,
                        "generation": 2,
                    },
                },
            )
        if path == f"/{CONNECTION}/handoff/ack":
            assert credential == "Bearer " + HANDOFF
            assert body == {"apiKey": OWNER_KEY}
            self.installed = True
            if self.lost_ack:
                self.lost_ack = False
                raise httpx.ReadTimeout("acknowledgement lost", request=request)
            return httpx.Response(200, json={"status": "confirmed", "generation": 2})
        pytest.fail(f"Unexpected management request: {path}")

    @property
    def registrations(self):
        return [call for call in self.calls if call[1] == "/registrations"]


@pytest.fixture(autouse=True)
def isolated_access(monkeypatch, tmp_path):
    monkeypatch.delenv("FLASHDATA_API_KEY", raising=False)
    monkeypatch.setenv("FLASHDATA_TRANSCRIPT_STATE_DIR", str(tmp_path / "private-state"))


@pytest.fixture
def server():
    return Server()


def manager(server, *, verifier=None, registration_transport="cli"):
    return AuthManager(
        transport=httpx.MockTransport(server.handler),
        verifier=verifier,
        registration_transport=registration_transport,
    )


def test_trial_registers_once_and_reuses_saved_access(server):
    with manager(server) as auth:
        first = auth.trial()
    assert first["status"] == "trial"
    assert first["trial_request_counts"]["youtube_transcript"] == 100
    assert TRIAL_KEY not in json.dumps(first)
    assert SETUP not in json.dumps(first)
    assert HANDOFF not in json.dumps(first)
    assert resolve_api_key() == TRIAL_KEY
    with manager(server) as auth:
        assert auth.trial()["connection_id"] == CONNECTION
        assert auth.status()["status"] == "trial"
    assert len(server.registrations) == 1


def test_lost_registration_reuses_durable_proof_and_body(server):
    server.lost_registration = True
    with manager(server) as auth:
        with pytest.raises(AuthError, match="same auth command"):
            auth.trial()
        state = auth.store.read()
    assert state["phase"] == "registering"
    assert "credentials" not in state
    with manager(server) as auth:
        auth.trial()
    assert len(server.registrations) == 2
    assert server.registrations[0] == server.registrations[1]


def test_proof_is_persisted_before_registration_is_dispatched(server):
    def handler(request):
        if request.url.path.endswith("/registrations"):
            saved = AuthStore().read()
            assert saved["phase"] == "registering"
            assert request.headers["Authorization"] == "Bearer " + saved["registration"]["proof"]
            assert json.loads(request.content) == saved["registration"]["body"]
        return server.handler(request)

    with AuthManager(transport=httpx.MockTransport(handler)) as auth:
        auth.trial()


def test_existing_environment_and_explicit_keys_take_precedence(server, monkeypatch):
    with manager(server) as auth:
        auth.trial()
    monkeypatch.setenv("FLASHDATA_API_KEY", "existing-owner-key")
    previous = len(server.calls)
    with manager(server) as auth:
        assert auth.trial() == {
            "source": "environment",
            "status": "configured",
            "trial_created": False,
        }
        assert auth.status()["source"] == "environment"
    assert len(server.calls) == previous
    assert resolve_api_key() == "existing-owner-key"
    assert resolve_api_key("explicit-key") == "explicit-key"
    assert AuthStore().read()["credentials"]["apiKey"] == TRIAL_KEY


def test_empty_environment_key_does_not_switch_accounts(server, monkeypatch):
    monkeypatch.setenv("FLASHDATA_API_KEY", " ")
    with manager(server) as auth:
        with pytest.raises(AuthError, match="empty"):
            auth.trial()
    assert server.calls == []


def test_normal_client_never_registers_a_trial_implicitly():
    with pytest.raises(AuthError, match="auth trial"):
        TranscriptClient()
    assert AuthStore().read() is None


@pytest.mark.parametrize("status", [401, 403, 410, 429])
def test_invalid_or_expired_saved_access_never_creates_another_trial(server, status):
    with manager(server) as auth:
        auth.trial()
        before = auth.store.read()
        server.identity_error = status
        with pytest.raises(AuthError) as error:
            auth.trial()
        assert TRIAL_KEY not in str(error.value)
        assert auth.store.read() == before
    assert len(server.registrations) == 1


def test_local_expiry_stops_normal_fetch(server):
    with manager(server) as auth:
        auth.trial()
        state = auth.store.read()
        state["connection"]["trialExpiresAt"] = future(-1)
        auth.store.save(state)
    with pytest.raises(AuthError, match="expired"):
        resolve_api_key()


@pytest.mark.parametrize("mutation", ["unavailable", "origin"])
def test_discovery_is_checked_before_registering(server, mutation):
    if mutation == "unavailable":
        server.available = False
    else:
        server.data_origin = "https://untrusted.invalid"
    with manager(server) as auth:
        with pytest.raises(AuthError):
            auth.trial()
    assert server.registrations == []
    assert AuthStore().read() is None


def test_redirects_are_never_followed(server):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://untrusted.invalid"})

    with AuthManager(transport=httpx.MockTransport(handler)) as auth:
        with pytest.raises(AuthError, match="307"):
            auth.trial()
    assert len(calls) == 1
    assert calls[0].url.host == "api.flashdata.dev"


def test_saved_key_is_used_by_normal_sdk_request(server, response, monkeypatch):
    with manager(server) as auth:
        auth.trial()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "data.flashdata.dev"
        assert request.headers["X-API-Key"] == TRIAL_KEY
        return httpx.Response(200, json=response)

    def sdk_factory(**kwargs):
        return FlashData(**kwargs, transport=httpx.MockTransport(handler), trust_env=False)

    monkeypatch.setattr("flashdata_transcript.client.FlashData", sdk_factory)
    with TranscriptClient() as client:
        assert client.fetch("DEMO0000001", language="en").language_code == "en-orig"
    assert len(calls) == 1


def test_python_from_trial_uses_same_saved_connection(server, monkeypatch):
    monkeypatch.setattr(
        "flashdata_transcript.client.AuthManager",
        lambda state_dir, **kwargs: manager(server, **kwargs),
    )
    with TranscriptClient.from_trial() as client:
        assert client._sdk._key == TRIAL_KEY
    with TranscriptClient.from_trial() as client:
        assert client._sdk._key == TRIAL_KEY
    assert len(server.registrations) == 1
    assert server.registrations[0][3]["transport"] == "api"


def test_lost_python_registration_can_be_recovered_by_cli_with_same_body(server):
    server.lost_registration = True
    with manager(server, registration_transport="api") as auth:
        with pytest.raises(AuthError):
            auth.trial()
    with manager(server) as auth:
        auth.trial()
    assert server.registrations[0] == server.registrations[1]
    assert server.registrations[1][3]["transport"] == "api"


def test_claim_displays_only_canonical_url_and_separate_code_and_reuses_link(server):
    with manager(server) as auth:
        auth.trial()
        first = auth.claim()
        assert auth.claim() == first
    assert first["claim_url"] == f"https://flashdata.dev/connect/claim/{CLAIM}"
    assert first["confirmation_code"] == "12345678"
    assert "12345678" not in first["claim_url"]
    assert sum(call[1].endswith("/claims") for call in server.calls) == 1
    assert not any(call[1].endswith("/approve") for call in server.calls)


def test_claim_rejects_external_or_modified_urls():
    with pytest.raises(AuthError, match="claim URL"):
        AuthManager._claim_summary(
            {
                "claimId": CLAIM,
                "claimPath": f"https://untrusted.invalid/{CLAIM}",
                "confirmationCode": "12345678",
                "expiresAt": future(),
            }
        )


def test_finish_requires_browser_approval_and_does_not_auto_approve(server):
    with manager(server) as auth:
        auth.trial()
        auth.claim()
        assert auth.finish()["status"] == "awaiting_claim"
    assert not any(call[1].endswith("/handoff") for call in server.calls)
    assert not any(call[1].endswith("/approve") for call in server.calls)


def test_owner_handoff_saves_then_verifies_then_acknowledges(server):
    verified = []

    def verifier(store, connection):
        saved = AuthStore(store.directory).read()
        assert saved["phase"] == "handoff_pending"
        assert saved["credentials"]["apiKey"] == OWNER_KEY
        assert connection["ownership"] == "owned"
        assert not server.installed
        verified.append(True)

    with manager(server, verifier=verifier) as auth:
        auth.trial()
        server.approved = True
        result = auth.finish()
        saved = auth.store.read()
        assert result["status"] == "owned"
        assert saved["credentials"] == {"apiKey": OWNER_KEY}
        assert "registration" not in saved
        assert "claim" not in saved
        assert saved["connection"]["installed"] is True
        assert auth.trial()["status"] == "owned"
    assert verified == [True]
    assert server.installed
    assert len(server.registrations) == 1
    assert resolve_api_key() == OWNER_KEY


def test_verification_failure_preserves_handoff_without_ack_or_new_trial(server):
    def verifier(*_args):
        raise AuthError("Simulated verification failure")

    with manager(server, verifier=verifier) as auth:
        auth.trial()
        server.approved = True
        with pytest.raises(AuthError, match="verification"):
            auth.finish()
        assert auth.store.read()["phase"] == "handoff_pending"
        assert HANDOFF == auth.store.read()["credentials"]["handoffProof"]
        with pytest.raises(AuthError, match="handoff"):
            auth.trial()
    assert not server.installed
    with pytest.raises(AuthError, match="auth finish"):
        resolve_api_key()
    with manager(server, verifier=lambda *_args: None) as auth:
        assert auth.finish()["status"] == "owned"
    assert len(server.registrations) == 1
    assert sum(call[1].endswith("/handoff") for call in server.calls) == 1


def test_lost_ack_response_recovers_from_installed_state(server):
    with manager(server, verifier=lambda *_args: None) as auth:
        auth.trial()
        server.approved = True
        server.lost_ack = True
        with pytest.raises(AuthError, match="response unavailable"):
            auth.finish()
        assert auth.store.read()["phase"] == "handoff_pending"
        assert server.installed
    with manager(server, verifier=lambda *_args: None) as auth:
        assert auth.finish()["status"] == "owned"
    assert sum(call[1].endswith("/handoff") for call in server.calls) == 1
    assert sum(call[1].endswith("/handoff/ack") for call in server.calls) == 1


def test_polling_respects_server_delay(server, monkeypatch):
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        server.approved = True

    monkeypatch.setattr("flashdata_transcript.auth.time.sleep", sleep)
    with manager(server, verifier=lambda *_args: None) as auth:
        auth.trial()
        assert auth.finish(wait=True)["status"] == "owned"
    assert sleeps == [5]


@pytest.mark.parametrize("status", ["expired", "revoked", "blocked", "handoff_expired"])
def test_finish_terminal_errors_do_not_replace_trial(server, status):
    with manager(server) as auth:
        auth.trial()
        server.poll_status = status
        with pytest.raises(AuthError):
            auth.finish()
    assert len(server.registrations) == 1


def test_corrupt_state_is_never_replaced_by_setup(server):
    store = AuthStore()
    store.save({"version": 1, "phase": "broken"})
    before = store.path.read_bytes()
    with manager(server) as auth:
        with pytest.raises(AuthError):
            auth.trial()
    assert store.path.read_bytes() == before
    assert server.calls == []


def test_state_storage_round_trip_and_fresh_process_read():
    store = AuthStore()
    value = {"version": 1, "phase": "test", "secret": TRIAL_KEY}
    store.save(value)
    assert store.read() == value
    if os.name == "nt":
        assert TRIAL_KEY.encode() not in store.path.read_bytes()
        assert b"DPAPI" in store.path.read_bytes()
    else:
        assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from flashdata_transcript._auth_store import AuthStore; "
            "s=AuthStore().read(); print(s['version'], s['phase'], len(s['secret']))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "1 test 46"


def test_authentication_lock_releases_after_error():
    store = AuthStore()
    with pytest.raises(RuntimeError), store.locked():
        with pytest.raises(AuthError, match="Another authentication"):
            with AuthStore().locked():
                pytest.fail("Concurrent lock acquired")
        raise RuntimeError("interrupted")
    with AuthStore().locked():
        pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_world_readable_credentials_are_rejected():
    store = AuthStore()
    store.save({"version": 1})
    store.path.chmod(0o644)
    with pytest.raises(AuthError, match="0600"):
        store.read()


def test_cli_auth_output_contains_no_credentials(server, monkeypatch, capsys):
    monkeypatch.setattr("flashdata_transcript.cli.AuthManager", lambda state_dir: manager(server))
    assert main(["auth", "trial"]) == 0
    assert main(["auth", "status"]) == 0
    assert main(["auth", "claim"]) == 0
    assert main(["auth", "finish"]) == 2
    output = capsys.readouterr()
    for secret in [TRIAL_KEY, SETUP, HANDOFF]:
        assert secret not in output.out + output.err
    assert "confirmation_code" in output.out


def test_fresh_verifier_process_receives_only_paths_and_public_identifiers(server, monkeypatch):
    captured = []

    def subprocess_run(command, **kwargs):
        captured.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="verified\n", stderr="")

    monkeypatch.setattr("flashdata_transcript.auth.subprocess.run", subprocess_run)
    with manager(server) as auth:
        auth.trial()
        server.approved = True
        assert auth.finish()["status"] == "owned"
    command, options = captured[0]
    assert command[1:3] == ["-m", "flashdata_transcript._verify_auth"]
    assert command[-2:] == [CONNECTION, "2"]
    assert OWNER_KEY not in json.dumps([command, options])


def test_modified_registration_body_is_not_replayed_or_reset(server):
    server.lost_registration = True
    with manager(server) as auth:
        with pytest.raises(AuthError):
            auth.trial()
        state = deepcopy(auth.store.read())
        state["registration"]["body"]["name"] = "Changed name"
        auth.store.save(state)
        with pytest.raises(AuthError, match="registration differs"):
            auth.trial()
    assert len(server.registrations) == 1

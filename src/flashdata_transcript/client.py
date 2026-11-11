"""Transcript workflows on top of the official FlashData SDK."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from flashdata import FlashData

from .auth import AuthManager, resolve_api_key
from .errors import ResponseError, RetrievalFailed
from .models import LanguageError, Transcript, TranscriptResult
from .validation import caption_origin, language_code, language_codes, video_id


def _payload(response: Any, expected_id: str) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ResponseError("Expected a JSON response from FlashData.")
    if response.get("status") == "failed":
        raise RetrievalFailed(response.get("id"))
    if response.get("status") != "done":
        raise ResponseError("The transcript request did not finish. Check History before retrying.")
    results = response.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise ResponseError("Expected exactly one video result; no result was silently discarded.")
    payload = results[0]
    if payload.get("videoId") != expected_id:
        raise ResponseError("The response video ID does not match the request.")
    return payload


class TranscriptClient:
    """Fetch existing YouTube captions through FlashData. No automatic request retries."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 120,
        sdk: FlashData | None = None,
        state_dir: str | Path | None = None,
    ) -> None:
        if sdk is not None and api_key is not None:
            raise ValueError("Provide an API key or an existing SDK client, not both.")
        self._sdk = (
            sdk
            if sdk is not None
            else FlashData(api_key=resolve_api_key(api_key, state_dir), timeout=timeout)
        )
        self._owns_sdk = sdk is None

    @classmethod
    def from_trial(
        cls, *, state_dir: str | Path | None = None, timeout: float = 120
    ) -> TranscriptClient:
        """Explicitly create/reuse live trial access, then fetch normally with its saved key."""
        with AuthManager(state_dir, registration_transport="api") as manager:
            manager.trial()
        return cls(state_dir=state_dir, timeout=timeout)

    def __repr__(self) -> str:
        return "<TranscriptClient>"

    def __enter__(self) -> TranscriptClient:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_sdk:
            self._sdk.close()

    def fetch(self, video: str, *, language: str | None = None, auto: bool = True) -> Transcript:
        """Fetch one caption track. Accept a video ID or YouTube video URL."""
        identifier = video_id(video)
        params: dict[str, Any] = {"auto": caption_origin(auto)}
        if language is not None:
            params["language"] = language_code(language)
        response = self._sdk.youtube.transcript(identifier, **params)
        transcript = Transcript.from_api(_payload(response, identifier))
        if transcript.is_auto_generated != auto:
            raise ResponseError("The returned caption origin does not match the request.")
        if language is not None:
            selected = transcript.requested_language_code or transcript.language_code
            if selected != language:
                raise ResponseError("The returned language does not match the request.")
        return transcript

    def fetch_languages(
        self, video: str, languages: Sequence[str], *, auto: bool = True
    ) -> TranscriptResult:
        """Try every requested language in one request; preserve per-language failures."""
        identifier = video_id(video)
        requested = language_codes(languages)
        response = self._sdk.youtube.transcript(
            identifier, language=requested, auto=caption_origin(auto)
        )
        payload = _payload(response, identifier)
        if not isinstance(payload.get("tracks"), list) or not isinstance(
            payload.get("errors"), list
        ):
            raise ResponseError("Expected tracks and errors arrays for a language-array request.")
        tracks = tuple(Transcript.from_api(value) for value in payload["tracks"])
        errors = tuple(LanguageError.from_api(value) for value in payload["errors"])
        for track in tracks:
            if track.video_id != identifier or track.is_auto_generated != auto:
                raise ResponseError("A returned track does not match the requested video/origin.")
        covered = [track.requested_language_code or track.language_code for track in tracks]
        covered += [error.language_code for error in errors]
        if Counter(covered) != Counter(requested):
            raise ResponseError(
                "The response did not account for each requested language exactly once."
            )
        return TranscriptResult(identifier, tracks, errors, response.get("id"))

    def languages(self, video: str) -> list[str]:
        """List available language codes using Metadata; this is a separate API request."""
        identifier = video_id(video)
        response = self._sdk.youtube.metadata(
            identifier, include_formats=False, include_chapters=False
        )
        payload = _payload(response, identifier)
        codes = payload.get("transcriptLanguages")
        if not isinstance(codes, list) or any(
            not isinstance(code, str) or not code for code in codes
        ):
            raise ResponseError("Expected transcriptLanguages in the Metadata response.")
        return sorted(set(codes))

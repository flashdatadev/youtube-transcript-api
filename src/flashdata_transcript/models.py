"""Typed transcripts with explicit seconds, language, and caption origin."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import ResponseError
from .validation import video_id


def _text(value: Any, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ResponseError(f"Expected a string for {field}.")
    return value


def _seconds(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResponseError(f"Expected seconds for {field}.")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ResponseError(f"Expected finite, non-negative seconds for {field}.")
    return result


@dataclass(frozen=True)
class Segment:
    text: str
    start: float
    end: float

    def __post_init__(self) -> None:
        _text(self.text, "segment.text", empty=True)
        start, end = _seconds(self.start, "segment.start"), _seconds(self.end, "segment.end")
        if end < start:
            raise ResponseError("A segment ends before it starts.")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, value: Any) -> Segment:
        if not isinstance(value, dict):
            raise ResponseError("Expected a segment object.")
        return cls(
            text=_text(value.get("text"), "segment.text", empty=True),
            start=_seconds(value.get("start"), "segment.start"),
            end=_seconds(value.get("end"), "segment.end"),
        )


@dataclass(frozen=True)
class Transcript:
    video_id: str
    language_code: str
    is_auto_generated: bool
    segments: tuple[Segment, ...]
    full_text: str
    language_name: str | None = None
    requested_language_code: str | None = None
    is_demo: bool = False

    def __post_init__(self) -> None:
        try:
            identifier = video_id(self.video_id)
        except ValueError as exc:
            raise ResponseError("A transcript must contain a valid video ID.") from exc
        if identifier != self.video_id:
            raise ResponseError("A transcript must contain a video ID, not a URL.")
        _text(self.language_code, "language_code")
        _text(self.full_text, "full_text", empty=True)
        if not isinstance(self.is_auto_generated, bool) or not isinstance(self.is_demo, bool):
            raise ResponseError("Caption origin and demo flags must be booleans.")
        if self.language_name is not None:
            _text(self.language_name, "language_name", empty=True)
        if self.requested_language_code is not None:
            _text(self.requested_language_code, "requested_language_code")
        if not isinstance(self.segments, tuple) or any(
            not isinstance(segment, Segment) for segment in self.segments
        ):
            raise ResponseError("segments must be a tuple of Segment objects.")
        if not self.segments:
            raise ResponseError("No timestamped segments were returned.")

    @property
    def source_url(self) -> str | None:
        if self.is_demo:
            return None
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "source_url": self.source_url,
            "language_code": self.language_code,
            "requested_language_code": self.requested_language_code,
            "language_name": self.language_name,
            "is_auto_generated": self.is_auto_generated,
            "is_demo": self.is_demo,
            "full_text": self.full_text,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, value: Any) -> Transcript:
        """Read this toolkit's normalized JSON output."""
        if not isinstance(value, dict) or not isinstance(value.get("segments"), list):
            raise ResponseError("Expected transcript JSON with a segments array.")
        return cls(
            video_id=_text(value.get("video_id"), "video_id"),
            language_code=_text(value.get("language_code"), "language_code"),
            language_name=value.get("language_name"),
            requested_language_code=value.get("requested_language_code"),
            is_auto_generated=value.get("is_auto_generated"),
            is_demo=value.get("is_demo", False),
            full_text=_text(value.get("full_text"), "full_text", empty=True),
            segments=tuple(Segment.from_dict(segment) for segment in value["segments"]),
        )

    @classmethod
    def from_api(cls, value: Any) -> Transcript:
        """Read one FlashData results item or one item in its tracks array."""
        if not isinstance(value, dict) or not isinstance(value.get("segments"), list):
            raise ResponseError("Expected a FlashData transcript with a segments array.")
        return cls.from_dict(
            {
                "video_id": value.get("videoId"),
                "language_code": value.get("languageCode"),
                "language_name": value.get("languageName"),
                "requested_language_code": value.get("requestedLanguageCode"),
                "is_auto_generated": value.get("isAutoGenerated"),
                "full_text": value.get("fullText"),
                "segments": value["segments"],
            }
        )


@dataclass(frozen=True)
class LanguageError:
    language_code: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"language_code": self.language_code, "code": self.code, "message": self.message}

    @classmethod
    def from_api(cls, value: Any) -> LanguageError:
        if not isinstance(value, dict):
            raise ResponseError("Expected a per-language error object.")
        return cls(
            _text(value.get("languageCode"), "error.languageCode"),
            _text(value.get("code"), "error.code"),
            _text(value.get("message"), "error.message"),
        )


@dataclass(frozen=True)
class TranscriptResult:
    video_id: str
    tracks: tuple[Transcript, ...]
    errors: tuple[LanguageError, ...]
    job_id: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.tracks) and not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "job_id": self.job_id,
            "tracks": [track.to_dict() for track in self.tracks],
            "errors": [error.to_dict() for error in self.errors],
        }

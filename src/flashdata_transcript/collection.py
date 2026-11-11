"""Sequential transcript collection with durable checkpoints and explicit retries."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from flashdata import APIError, FlashDataError, ValidationError

from .client import TranscriptClient
from .errors import CollectionStopped, ResponseError, RetrievalFailed
from .validation import caption_origin, language_code, video_id


def read_videos(lines: Iterable[str], *, limit: int = 100) -> list[str]:
    """Validate and deduplicate input before spending credits. Never truncate silently."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000 videos.")
    videos: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        identifier = video_id(line)
        if identifier not in seen:
            seen.add(identifier)
            videos.append(identifier)
        if len(videos) > limit:
            raise ValueError(f"Input exceeds the {limit}-video limit; raise --limit explicitly.")
    if not videos:
        raise ValueError("Input contains no YouTube videos.")
    return videos


def _atomic_write(path: Path, text: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _save(state: dict[str, Any], checkpoint: Path, output: Path) -> None:
    # The checkpoint is authoritative. Resume can regenerate interrupted JSONL output.
    _atomic_write(checkpoint, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    records = [state["entries"][identifier] for identifier in state["videos"]]
    _atomic_write(output, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))


def _load(checkpoint: Path, config: dict[str, Any], videos: list[str]) -> dict[str, Any]:
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Unsupported collection checkpoint.")
    if state.get("config") != config or state.get("videos") != videos:
        raise ValueError("Resume needs the same video list, language, and caption origin.")
    entries = state.get("entries")
    statuses = {"pending", "in_progress", "success", "failed", "uncertain"}
    if not isinstance(entries, dict) or set(entries) != set(videos):
        raise ValueError("The collection checkpoint is incomplete.")
    for identifier, entry in entries.items():
        if (
            not isinstance(entry, dict)
            or entry.get("video_id") != identifier
            or entry.get("status") not in statuses
        ):
            raise ValueError("The collection checkpoint contains an invalid entry.")
        if entry["status"] == "success" and not isinstance(entry.get("result"), dict):
            raise ValueError("A completed checkpoint entry has no result; refusing to resubmit.")
        if entry["status"] == "in_progress":
            entry.update(status="uncertain", error="Interrupted request; check console History.")
    return state


def collect(
    client: TranscriptClient,
    videos: Iterable[str],
    output: str | Path,
    *,
    language: str = "en",
    auto: bool = True,
    limit: int = 100,
    resume: bool = False,
    retry_failed: bool = False,
    retry_uncertain: bool = False,
) -> dict[str, int]:
    """Write JSONL plus <output>.checkpoint.json. Successful requests are never retried.

    This uses one realtime API request per unique video, not the server-side bulk
    API. Pending work resumes automatically. Failed/uncertain work needs an explicit
    retry flag; a transport failure stops the current run after saving its status.
    """
    identifiers = read_videos(videos, limit=limit)
    config = {"language": language_code(language), "auto": caption_origin(auto)}
    if (retry_failed or retry_uncertain) and not resume:
        raise ValueError("Retry flags require --resume.")
    output = Path(output).resolve()
    checkpoint = output.with_name(output.name + ".checkpoint.json")
    lock = output.with_name(output.name + ".lock")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            f"Collection is locked: {lock}. If no runner is active, remove that lock and resume."
        ) from exc
    os.close(descriptor)
    try:
        if resume:
            state = _load(checkpoint, config, identifiers)
        else:
            if output.exists() or checkpoint.exists():
                raise FileExistsError(
                    "Collection output already exists. Use --resume or a new path."
                )
            state = {
                "version": 1,
                "config": config,
                "videos": identifiers,
                "entries": {key: {"video_id": key, "status": "pending"} for key in identifiers},
            }
        _save(state, checkpoint, output)
        for identifier in identifiers:
            entry = state["entries"][identifier]
            status = entry["status"]
            if status == "success":
                continue
            if status == "failed" and not retry_failed:
                continue
            if status == "uncertain" and not retry_uncertain:
                continue
            entry.clear()
            entry.update(video_id=identifier, status="in_progress")
            _save(state, checkpoint, output)
            stop = False
            try:
                result = client.fetch_languages(identifier, [language], auto=auto)
                entry.update(status="success" if result.ok else "failed", result=result.to_dict())
            except RetrievalFailed as exc:
                entry.update(status="failed", job_id=exc.job_id, error="Transcript job failed.")
            except ValidationError:
                entry.update(status="failed", error="SDK validation failed before submission.")
                stop = True
            except APIError as exc:
                certain = 400 <= exc.status_code < 500 and exc.status_code != 408
                entry.update(
                    status="failed" if certain else "uncertain",
                    error=f"FlashData HTTP {exc.status_code}.",
                )
                stop = not certain or exc.status_code in {401, 402, 403, 429}
            except (FlashDataError, ResponseError):
                entry.update(
                    status="uncertain", error="Response unavailable; check console History."
                )
                stop = True
            _save(state, checkpoint, output)
            if stop:
                raise CollectionStopped(
                    "Collection saved. Check credentials, credits, or console History. "
                    "Failed/uncertain records are skipped unless you explicitly retry them."
                )
        return {
            status: sum(entry["status"] == status for entry in state["entries"].values())
            for status in ("success", "failed", "uncertain", "pending")
        }
    finally:
        lock.unlink(missing_ok=True)

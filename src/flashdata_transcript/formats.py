"""Local transcript exports; these functions never make API requests."""

from __future__ import annotations

import csv
import html
import io
import json
import math
import re

from .models import Transcript

FORMATS = ("json", "txt", "srt", "vtt", "csv", "md")


def timestamp(seconds: float, *, separator: str = ".") -> str:
    """Round seconds to milliseconds, including carry into minutes/hours."""
    millis = math.floor(seconds * 1000 + 0.5)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _cue_text(text: str) -> str:
    # Blank lines delimit subtitle cues; markup in a caption must remain literal.
    lines = [line.strip() for line in text.replace("\r", "\n").splitlines() if line.strip()]
    return html.escape("\n".join(lines), quote=False)


def render(transcript: Transcript, format: str = "json") -> str:
    """Export JSON, text, SRT, WebVTT, CSV, or Markdown with source timestamps."""
    if format not in FORMATS:
        raise ValueError(f"Choose one of: {', '.join(FORMATS)}.")
    if format == "json":
        return json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if format == "txt":
        return transcript.full_text.rstrip() + "\n"
    if format in {"srt", "vtt"}:
        separator = "," if format == "srt" else "."
        cues = []
        for segment in transcript.segments:
            content = _cue_text(segment.text)
            if not content:
                continue
            start = math.floor(segment.start * 1000 + 0.5)
            end = max(start + 1, math.floor(segment.end * 1000 + 0.5))
            times = (
                f"{timestamp(start / 1000, separator=separator)} --> "
                f"{timestamp(end / 1000, separator=separator)}"
            )
            index = f"{len(cues) + 1}\n" if format == "srt" else ""
            cues.append(f"{index}{times}\n{content}")
        prefix = "WEBVTT\n\n" if format == "vtt" else ""
        return prefix + "\n\n".join(cues) + "\n\n"
    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["video_id", "language_code", "start", "end", "text"])
        for segment in transcript.segments:
            writer.writerow(
                [
                    transcript.video_id,
                    transcript.language_code,
                    segment.start,
                    segment.end,
                    segment.text,
                ]
            )
        return output.getvalue()
    lines = [f"# Transcript: {transcript.video_id}", ""]
    if transcript.is_demo:
        lines.extend(["Synthetic demo captions; no source video.", ""])
    for segment in transcript.segments:
        label = timestamp(segment.start)
        link = f"{transcript.source_url}&t={math.floor(segment.start)}s"
        heading = f"[{label}]({link})" if transcript.source_url else label
        text = html.escape(" ".join(segment.text.split()), quote=False)
        text = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)
        lines.append(f"- **{heading}** {text}")
    return "\n".join(lines) + "\n"

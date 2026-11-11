"""Build bounded text chunks with video provenance, without an LLM dependency."""

from __future__ import annotations

import math
import textwrap
from typing import Any

from .models import Transcript


def chunk_transcript(transcript: Transcript, *, max_chars: int = 1200) -> list[dict[str, Any]]:
    """Group consecutive caption text; preserve source segment times for every chunk.

    The limit counts characters, not tokens. A long caption may be split across
    chunks, each retaining that caption's original start/end rather than invented
    word-level timestamps. Overlapping source captions keep their original text.
    """
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 20:
        raise ValueError("max_chars must be an integer of at least 20.")
    chunks: list[dict[str, Any]] = []
    texts: list[str] = []
    start = end = 0.0

    def flush() -> None:
        if not texts:
            return
        source = transcript.source_url
        chunks.append(
            {
                "chunk_id": f"{transcript.video_id}:{transcript.language_code}:{len(chunks)}",
                "video_id": transcript.video_id,
                "language_code": transcript.language_code,
                "is_auto_generated": transcript.is_auto_generated,
                "is_demo": transcript.is_demo,
                "start": start,
                "end": end,
                "text": " ".join(texts),
                "source_url": f"{source}&t={math.floor(start)}s" if source else None,
            }
        )
        texts.clear()

    for segment in transcript.segments:
        text = " ".join(segment.text.split())
        pieces = textwrap.wrap(text, width=max_chars, break_on_hyphens=False)
        for piece in pieces:
            if texts and len(" ".join(texts)) + 1 + len(piece) > max_chars:
                flush()
            if not texts:
                start, end = segment.start, segment.end
            else:
                start, end = min(start, segment.start), max(end, segment.end)
            texts.append(piece)
    flush()
    return chunks

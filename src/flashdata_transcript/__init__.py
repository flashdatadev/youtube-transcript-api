"""YouTube Transcript API Toolkit, maintained by FlashData."""

from .chunks import chunk_transcript
from .client import TranscriptClient
from .collection import collect
from .errors import CollectionStopped, ResponseError, RetrievalFailed, TranscriptError
from .formats import render
from .models import LanguageError, Segment, Transcript, TranscriptResult

__version__ = "0.1.0"
__all__ = [
    "CollectionStopped",
    "LanguageError",
    "ResponseError",
    "RetrievalFailed",
    "Segment",
    "Transcript",
    "TranscriptClient",
    "TranscriptError",
    "TranscriptResult",
    "chunk_transcript",
    "collect",
    "render",
]

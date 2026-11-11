"""YouTube Transcript API Toolkit, maintained by FlashData."""

from .chunks import chunk_transcript
from .client import TranscriptClient
from .collection import collect
from .errors import AuthError, CollectionStopped, ResponseError, RetrievalFailed, TranscriptError
from .formats import render
from .models import LanguageError, Segment, Transcript, TranscriptResult

__version__ = "0.2.0"
__all__ = [
    "AuthError",
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

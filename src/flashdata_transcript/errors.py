"""Errors specific to transcript parsing and collection."""


class TranscriptError(Exception):
    """Base error for this toolkit; HTTP errors use flashdata.APIError."""


class ResponseError(TranscriptError):
    """The response cannot be read without losing or mislabelling data."""


class RetrievalFailed(TranscriptError):
    """FlashData returned a completed, failed job."""

    def __init__(self, job_id: str | None = None):
        self.job_id = job_id
        super().__init__("Transcript retrieval failed. Check the job in the FlashData console.")


class CollectionStopped(TranscriptError):
    """The collection checkpoint was saved and needs an explicit recovery choice."""

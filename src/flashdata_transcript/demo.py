"""Original, synthetic captions for an offline example. No real video is fetched."""

from .models import Segment, Transcript


def sample_transcript() -> Transcript:
    segments = (
        Segment("Welcome to this synthetic transcript demo.", 0.0, 3.2),
        Segment("Each caption has text, a start time, and an end time.", 3.2, 7.5),
        Segment("Export subtitles or build searchable chunks from the same response.", 7.5, 12.8),
        Segment("A real transcript keeps its video ID and timestamped source links.", 12.8, 18.0),
    )
    return Transcript(
        video_id="DEMO0000001",
        language_code="en",
        language_name="English",
        is_auto_generated=False,
        is_demo=True,
        full_text=" ".join(segment.text for segment in segments),
        segments=segments,
    )

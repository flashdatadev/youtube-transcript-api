import csv
import io
import json
from dataclasses import replace

import pytest

from flashdata_transcript import ResponseError, Segment, Transcript, chunk_transcript, render
from flashdata_transcript.demo import sample_transcript
from flashdata_transcript.formats import timestamp
from flashdata_transcript.validation import language_codes, video_id


@pytest.mark.parametrize(
    "value",
    [
        "DEMO0000001",
        "https://www.youtube.com/watch?v=DEMO0000001&t=9",
        "https://youtu.be/DEMO0000001?si=test",
        "youtube.com/shorts/DEMO0000001",
        "https://youtube.com/live/DEMO0000001",
        "https://www.youtube-nocookie.com/embed/DEMO0000001",
        "https://m.youtube.com/watch?v=DEMO0000001",
        " https://youtube.com/embed/DEMO0000001 ",
    ],
)
def test_video_inputs(value):
    assert video_id(value) == "DEMO0000001"


@pytest.mark.parametrize(
    "value",
    [
        "bad",
        "https://example.com/watch?v=DEMO0000001",
        "https://youtube.com.evil.test/watch?v=DEMO0000001",
        "https://youtube.com/playlist?list=DEMO0000001",
        "https://youtube.com/watch?v=DEMO0000001&v=DEMO0000002",
        "file://youtube.com/watch?v=DEMO0000001",
        "https://user@youtube.com/watch?v=DEMO0000001",
    ],
)
def test_invalid_video_inputs(value):
    with pytest.raises(ValueError):
        video_id(value)


@pytest.mark.parametrize("value", [[], ["en", "en"], "en", [""], [str(i) for i in range(11)]])
def test_language_array_bounds(value):
    with pytest.raises(ValueError):
        language_codes(value)


def test_language_codes_are_preserved():
    assert language_codes(["en", "en-orig", "zh-Hans"]) == ["en", "en-orig", "zh-Hans"]


@pytest.mark.parametrize("start,end", [(2, 1), (-1, 2), (True, 3), (0, float("inf"))])
def test_invalid_timing_rejected(start, end):
    with pytest.raises(ResponseError):
        Segment("text", start, end)


def test_json_round_trip_and_synthetic_provenance():
    transcript = sample_transcript()
    assert Transcript.from_dict(json.loads(render(transcript))) == transcript
    assert transcript.source_url is None
    assert "youtube.com" not in render(transcript, "md")


def test_subtitle_timestamps_and_escaping():
    transcript = replace(
        sample_transcript(),
        segments=(
            Segment("<b>Literal</b> & text\n\nNext line", 59.9996, 61.0014),
            Segment("Tiny cue", 62, 62),
            Segment("  ", 63, 64),
        ),
    )
    srt = render(transcript, "srt")
    assert srt == (
        "1\n00:01:00,000 --> 00:01:01,001\n&lt;b&gt;Literal&lt;/b&gt; &amp; text\nNext line\n\n"
        "2\n00:01:02,000 --> 00:01:02,001\nTiny cue\n\n"
    )
    vtt = render(transcript, "vtt")
    assert vtt.startswith("WEBVTT\n\n00:01:00.000 --> 00:01:01.001")
    assert timestamp(3599.9999) == "01:00:00.000"


def test_csv_round_trip_and_markdown_escaping():
    text = '中文, "quoted"\n[link](javascript:alert) <script>'
    transcript = replace(sample_transcript(), is_demo=False, segments=(Segment(text, 1, 2),))
    row = list(csv.DictReader(io.StringIO(render(transcript, "csv"))))[0]
    assert row["text"] == text
    markdown = render(transcript, "md")
    assert "watch?v=DEMO0000001&t=1s" in markdown
    assert "\\[link\\]" in markdown
    assert "<script>" not in markdown


def test_chunks_have_bounds_and_source_timing():
    transcript = replace(
        sample_transcript(),
        is_demo=False,
        segments=(
            Segment("A long caption " * 30, 2.2, 11.9),
            Segment("Last caption.", 13, 14),
        ),
    )
    chunks = chunk_transcript(transcript, max_chars=80)
    assert len(chunks) > 2
    assert all(len(chunk["text"]) <= 80 for chunk in chunks)
    assert " ".join(chunk["text"] for chunk in chunks) == " ".join(
        " ".join(segment.text.split()) for segment in transcript.segments
    )
    assert chunks[0]["start"] == 2.2
    assert chunks[0]["end"] == 11.9
    assert chunks[0]["source_url"].endswith("&t=2s")
    assert chunks[-1]["end"] == 14


def test_chunks_split_long_unbroken_words_and_demo_has_no_source():
    transcript = replace(sample_transcript(), segments=(Segment("x" * 90, 0, 1),))
    chunks = chunk_transcript(transcript, max_chars=20)
    assert all(len(chunk["text"]) <= 20 for chunk in chunks)
    assert "".join(chunk["text"] for chunk in chunks) == "x" * 90
    assert all(chunk["source_url"] is None for chunk in chunks)


@pytest.mark.parametrize("size", [0, -1, 1, True, 20.5])
def test_invalid_chunk_sizes(size):
    with pytest.raises(ValueError):
        chunk_transcript(sample_transcript(), max_chars=size)

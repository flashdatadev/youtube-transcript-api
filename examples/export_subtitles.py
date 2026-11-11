"""Fetch once and export all formats: python examples/export_subtitles.py VIDEO_ID"""

import argparse
from pathlib import Path

from flashdata_transcript import TranscriptClient, render
from flashdata_transcript.formats import FORMATS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("video")
parser.add_argument("--language", default="en")
parser.add_argument("--manual", action="store_true")
parser.add_argument("--output", default="output/exports")
args = parser.parse_args()
directory = Path(args.output)
directory.mkdir(parents=True, exist_ok=False)

with TranscriptClient() as client:
    transcript = client.fetch(args.video, language=args.language, auto=not args.manual)
for format in FORMATS:
    path = directory / f"{transcript.video_id}.{format}"
    path.write_text(render(transcript, format), encoding="utf-8")
    print(path)

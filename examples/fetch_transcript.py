"""Fetch a transcript: python examples/fetch_transcript.py VIDEO_ID --language en"""

import argparse

from flashdata_transcript import TranscriptClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("video")
parser.add_argument("--language", default="en")
parser.add_argument("--manual", action="store_true")
args = parser.parse_args()

with TranscriptClient() as client:
    transcript = client.fetch(args.video, language=args.language, auto=not args.manual)
print(transcript.full_text)
for segment in transcript.segments:
    print(f"{segment.start:.3f} --> {segment.end:.3f}: {segment.text}")

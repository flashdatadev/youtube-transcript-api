"""Fetch several languages: python examples/multiple_languages.py VIDEO_ID en es"""

import argparse
import json

from flashdata_transcript import TranscriptClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("video")
parser.add_argument("languages", nargs="+")
parser.add_argument("--manual", action="store_true")
args = parser.parse_args()

with TranscriptClient() as client:
    result = client.fetch_languages(args.video, args.languages, auto=not args.manual)
print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
raise SystemExit(0 if result.ok else 2)

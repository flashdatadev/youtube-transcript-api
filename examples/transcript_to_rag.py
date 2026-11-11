"""Chunk a saved transcript offline: python examples/transcript_to_rag.py transcript.json"""

import argparse
import json
from pathlib import Path

from flashdata_transcript import Transcript, chunk_transcript

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("input")
parser.add_argument("--max-chars", type=int, default=1200)
args = parser.parse_args()
transcript = Transcript.from_dict(json.loads(Path(args.input).read_text(encoding="utf-8")))
for chunk in chunk_transcript(transcript, max_chars=args.max_chars):
    print(json.dumps(chunk, ensure_ascii=False))

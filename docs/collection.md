# Collect YouTube transcripts with checkpoints

`collect` is a sequential client-side workflow. It is not a wrapper around the server-side bulk API.

1. Put video IDs or URLs in a UTF-8 text file, one per line.
2. Set `FLASHDATA_API_KEY` in your shell.
3. Run `flashdata-transcript collect videos.txt --output output/transcripts.jsonl --language en`.
4. Inspect each JSONL record's `status` and `result`.

The entire list is validated before the first request. Duplicate URLs and IDs for the same video produce one request. The default limit is 100 unique videos, with an explicit maximum of 1,000 via `--limit`. For larger workloads, use the FlashData SDK's async/bulk APIs.

## Files and statuses

Alongside `transcripts.jsonl`, the collector writes `transcripts.jsonl.checkpoint.json`. Keep both files. The checkpoint is authoritative and regenerates the JSONL file during resume.

| Status | Meaning | Normal resume behavior |
| --- | --- | --- |
| `pending` | No attempt yet | Submit |
| `in_progress` | Checkpoint saved immediately before a request | Treat as uncertain after interruption |
| `success` | All requested captions returned | Skip |
| `failed` | Known error or no matching caption track | Skip |
| `uncertain` | Request outcome was not confirmed | Skip |

The input order, normalized video IDs, language, and caption origin must match on resume. Do not edit checkpoints to reset completed videos. Choose a new output path for another language or input list.

```bash
# Continue pending entries
flashdata-transcript collect videos.txt --output output/transcripts.jsonl --language en --resume

# Retry known failures after addressing their cause
flashdata-transcript collect videos.txt --output output/transcripts.jsonl --language en --resume --retry-failed

# Explicitly retry uncertain requests after checking console History
flashdata-transcript collect videos.txt --output output/transcripts.jsonl --language en --resume --retry-uncertain
```

A lost response does not prove that the API request failed. Retrying it can consume additional credits. Completed successes are never retried by these flags. The collector stops on network/protocol failures, authentication/credit errors, and rate limits; it does not run an uncontrolled retry loop.

Only one process should write a collection. A sibling `.lock` file enforces this. If a process was forcibly terminated and left the lock behind, first confirm no runner is active, remove only that collection's `.lock` file, and resume normally. The persisted `in_progress` entry becomes `uncertain`.

## Reading the dataset

```python
import json
from pathlib import Path
from flashdata_transcript import Transcript, chunk_transcript

for line in Path("output/transcripts.jsonl").read_text(encoding="utf-8").splitlines():
    record = json.loads(line)
    if record["status"] != "success":
        continue
    for value in record["result"]["tracks"]:
        transcript = Transcript.from_dict(value)
        for chunk in chunk_transcript(transcript):
            print(chunk["source_url"], chunk["text"])
```

Collecting captions does not create embeddings or run summarization. Keep source URLs and language metadata when connecting the output to your downstream pipeline.

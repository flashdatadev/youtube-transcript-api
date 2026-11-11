# YouTube Transcript API Toolkit

[![CI](https://github.com/flashdatadev/youtube-transcript-api/actions/workflows/ci.yml/badge.svg)](https://github.com/flashdatadev/youtube-transcript-api/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Fetch YouTube transcripts in Python. Export subtitles. Build searchable transcript datasets.**

A Python client and CLI for the [FlashData YouTube Transcript API](https://flashdata.dev/docs/sources/youtube_transcript). Retrieve existing automatic or uploader-provided captions, keep their timestamps and language metadata, and export JSON, text, SRT, WebVTT, CSV, or Markdown.

Built on the [official FlashData Python SDK](https://github.com/flashdatadev/flashdata-python). Live requests use a FlashData API key; the offline demo and local conversions need no key.

[Quickstart](#quickstart) · [CLI](#command-line-usage) · [Examples](#runnable-python-examples) · [Language selection](#language-selection) · [Dataset collection](#collect-a-transcript-dataset) · [FAQ](#frequently-asked-questions)

## Quickstart

Requires **Python 3.10 or newer**.

```bash
git clone https://github.com/flashdatadev/youtube-transcript-api.git
cd youtube-transcript-api
python -m venv .venv
```

Activate the environment and install:

```bash
# macOS / Linux
source .venv/bin/activate
python -m pip install -e .
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

### Try it without an API key

```bash
flashdata-transcript demo
```

Open `output/demo/` to see synthetic captions in all six formats and timestamped JSONL chunks. This command makes **no network requests**. Use a new `--output` directory to run it again.

### Fetch your first transcript

[Get a FlashData API key](https://flashdata.dev/signup), then set it in your shell:

```bash
export FLASHDATA_API_KEY="your-flashdata-api-key"
```

```powershell
$env:FLASHDATA_API_KEY = "your-flashdata-api-key"
```

Replace `YOUR_VIDEO_ID` below with a YouTube video ID or watch URL that has captions:

```python
from flashdata_transcript import TranscriptClient

with TranscriptClient() as client:
    transcript = client.fetch("YOUR_VIDEO_ID", language="en")

print(transcript.full_text)
for segment in transcript.segments:
    print(f"{segment.start:.2f}–{segment.end:.2f}: {segment.text}")
```

The client also accepts `youtu.be`, Shorts, live, and embed video URLs. It validates inputs before making a request.

## What you can build

| Workflow | Included support |
| --- | --- |
| Retrieve a YouTube transcript | Python client and CLI; video IDs or URLs |
| Select captions | Automatic or uploader captions; explicit language codes |
| Collect several languages | Up to 10 distinct codes per request, with per-language errors |
| Export subtitles | SRT and WebVTT with millisecond timestamps |
| Store or analyze captions | Normalized JSON, plain text, and segment-level CSV |
| Create research notes | Markdown with links to the original video timestamps |
| Prepare RAG input | Bounded text chunks with video, language, start/end, and source links |
| Collect multiple videos | Deduplicated input, durable checkpoints, explicit retries, JSONL |

FlashData handles the YouTube retrieval infrastructure. Your Python application calls the API without configuring its own YouTube proxies or cookies.

## Language selection

### Automatic and manual captions

```python
from flashdata_transcript import TranscriptClient

with TranscriptClient() as client:
    automatic = client.fetch("YOUR_VIDEO_ID", language="en")
    manual = client.fetch("YOUR_VIDEO_ID", language="en", auto=False)
```

These are **two separate API requests**. `auto=True` requests existing automatic captions. `auto=False` requests uploader-provided captions; it does not silently fall back to automatic captions.

For automatic captions, `language="en"` prefers `en-orig` and then `en`. An explicit code such as `en-orig` requests that exact track. The result preserves both the returned `language_code` and, when different, `requested_language_code`. If no language is supplied, the API prefers `en-orig`, then `en`.

### Discover available language codes

```python
with TranscriptClient() as client:
    print(client.languages("YOUR_VIDEO_ID"))
```

Language discovery makes a separate **YouTube Metadata API** request. It returns available codes across caption origins; the list does not label each code as automatic or uploader-provided.

### Fetch several languages and keep partial results

```python
with TranscriptClient() as client:
    result = client.fetch_languages("YOUR_VIDEO_ID", ["en", "es", "zh-Hans"])

for track in result.tracks:
    print(track.language_code, track.full_text)
for error in result.errors:
    print(error.language_code, error.code, error.message)
```

Every code in the list is attempted. This is a multi-language request, not a preferred-language fallback list. `result.ok` is true only when at least one track is returned and no requested language has an error. Missing captions remain visible in `result.errors`, even when other tracks succeed.

## Export YouTube transcripts to SRT, VTT, text, or CSV

```python
from pathlib import Path
from flashdata_transcript import TranscriptClient, render

with TranscriptClient() as client:
    transcript = client.fetch("YOUR_VIDEO_ID", language="en")

Path("transcript.srt").write_text(render(transcript, "srt"), encoding="utf-8")
Path("transcript.vtt").write_text(render(transcript, "vtt"), encoding="utf-8")
Path("transcript.json").write_text(render(transcript, "json"), encoding="utf-8")
```

Fetch once, then export locally as often as needed. `render()` supports `json`, `txt`, `srt`, `vtt`, `csv`, and `md`. Segment `start` and `end` are seconds; `segment.duration` is calculated from them.

Example JSON from the offline demo, shortened to one segment:

```json
{
  "video_id": "DEMO0000001",
  "source_url": null,
  "language_code": "en",
  "requested_language_code": null,
  "language_name": "English",
  "is_auto_generated": false,
  "is_demo": true,
  "full_text": "Welcome to this synthetic transcript demo.",
  "segments": [
    {"text": "Welcome to this synthetic transcript demo.", "start": 0.0, "end": 3.2}
  ]
}
```

Live transcripts include a source video URL and `is_demo: false`. [Output format details](docs/output-formats.md).

## Command-line usage

The CLI reads `FLASHDATA_API_KEY` from your environment. `python -m flashdata_transcript` works as an alternative to `flashdata-transcript`.

```bash
# Fetch and save normalized JSON
flashdata-transcript fetch YOUR_VIDEO_ID --language en --output transcript.json

# Convert an existing JSON file locally; no additional API request
flashdata-transcript convert transcript.json --format srt --output transcript.srt
flashdata-transcript convert transcript.json --format vtt --output transcript.vtt
flashdata-transcript convert transcript.json --format csv --output transcript.csv

# Fetch uploader captions directly as text
flashdata-transcript fetch YOUR_VIDEO_ID --language en --manual --format txt

# Discover available language codes
flashdata-transcript languages YOUR_VIDEO_ID

# Fetch several languages; output includes successful tracks and errors
flashdata-transcript fetch-languages YOUR_VIDEO_ID --languages en es --output languages.json

# Prepare JSONL chunks from a saved transcript, locally
flashdata-transcript chunks transcript.json --max-chars 1200 --output chunks.jsonl
```

Existing output files are not overwritten. Exit codes: `0` success, `1` request/input/file error, `2` partial or failed collection/language results, `130` interrupted. Use `--help` on any command.

## Collect a transcript dataset

Create `videos.txt` with one video ID or URL per line. Blank lines and lines starting with `#` are ignored.

```text
# Replace these with your own video IDs or URLs
YOUR_VIDEO_ID
ANOTHER_VIDEO_ID
```

```bash
flashdata-transcript collect videos.txt --language en --output output/transcripts.jsonl

# Continue pending work without fetching completed videos again
flashdata-transcript collect videos.txt --language en --output output/transcripts.jsonl --resume
```

The collector validates the entire input, deduplicates equivalent IDs/URLs, and makes **one realtime request per unique video**, sequentially. It writes one JSONL record per video, including success/failure status, plus a checkpoint beside the output. The default limit is 100 unique videos; `--limit` can explicitly raise it to 1,000.

Successful records are never resubmitted. Failed or uncertain requests are skipped on normal resume. After checking the cause, use `--resume --retry-failed` or `--resume --retry-uncertain` to retry them explicitly. A request that lost its response may already have used credits.

[Collection and recovery guide](docs/collection.md) · [Large-scale async and bulk API reference](https://flashdata.dev/docs)

## Prepare transcript chunks for RAG

```python
from flashdata_transcript import chunk_transcript

chunks = chunk_transcript(transcript, max_chars=1200)
for chunk in chunks:
    print(chunk["text"])
    print(chunk["source_url"])  # Link to this part of the source video
```

Chunks retain `video_id`, `language_code`, caption origin, and segment start/end times. They can be fed into your embedding, search, summarization, or retrieval pipeline. Chunking uses character limits, not token counts, and does not call an LLM. A split caption keeps its original timing; the toolkit does not invent word-level alignment.

## Runnable Python examples

After installation, replace `YOUR_VIDEO_ID` in live commands:

| Example | Command |
| --- | --- |
| Fetch text and timestamps | `python examples/fetch_transcript.py YOUR_VIDEO_ID` |
| Request multiple languages | `python examples/multiple_languages.py YOUR_VIDEO_ID en es` |
| Export all subtitle/data formats | `python examples/export_subtitles.py YOUR_VIDEO_ID --output output/exports` |
| Build chunks from a saved transcript | `python examples/transcript_to_rag.py output/demo/transcript.json` |
| Offline exports | `flashdata-transcript demo --output output/demo` |

## Frequently asked questions

### Is this the same as the `youtube-transcript-api` PyPI package?

No. [`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) is an independent community library that retrieves transcripts directly from YouTube. This repository is FlashData's API-backed toolkit. Its Python import is `flashdata_transcript`, and its distribution name is `flashdata-youtube-transcript-api`.

Install this toolkit from the Git repository using the quickstart above. We do not use or replace the community package's import name.

### Do I need a Google YouTube Data API key?

No. Live calls use a **FlashData API key**. Google's official [`captions.download`](https://developers.google.com/youtube/data/v3/docs/captions/download) method requires OAuth authorization and permission to edit the video. That is a different access model from this toolkit.

### Is the YouTube Transcript API free?

The toolkit is open source under the MIT license. Local conversions, chunking, and the synthetic demo are free to run. Live FlashData requests consume API credits. See [current pricing](https://flashdata.dev/pricing) and your console for available trial credits and usage.

### Can it transcribe a video that has no captions?

This toolkit retrieves **existing YouTube caption tracks**. It does not run speech-to-text on audio. Missing captions or unavailable languages are returned as failures rather than fabricated transcript text.

### Does it translate transcripts?

It selects available caption language tracks; it does not provide a separate translation operation. For translation or summarization, pass the retrieved text to your chosen model or service.

### Can I process many videos?

Yes. Use `collect` for bounded sequential collections with checkpoints. For server-side async/bulk processing, use the [FlashData SDK](https://github.com/flashdatadev/flashdata-python) and [API documentation](https://flashdata.dev/docs).

### What if a request fails?

Check the caption origin, language, video availability, API permissions, and credits. The client preserves SDK errors and does not automatically repeat requests. [Troubleshooting](docs/troubleshooting.md) explains partial results, transport failures, and recovery.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m build
```

Tests use synthetic fixtures and the SDK's HTTP mock transport; no paid API key is required. See [CONTRIBUTING.md](CONTRIBUTING.md) for the test and contribution workflow.

## More FlashData tools

- [YouTube Data API Toolkit](https://github.com/flashdatadev/youtube-data-api): search, video metadata, channels, and dataset examples.
- [FlashData Python SDK](https://github.com/flashdatadev/flashdata-python): all API sources, async requests, and bulk workflows.
- [YouTube Transcript API reference](https://flashdata.dev/docs/sources/youtube_transcript): request parameters and raw response fields.
- [Support](https://flashdata.dev/contact) · [MIT license](LICENSE)

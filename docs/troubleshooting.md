# Troubleshooting YouTube transcript requests

## API key and installation

Install this repository with `python -m pip install -e .`, then run `python -m flashdata_transcript --help`. If the `flashdata-transcript` command is not found, activate the virtual environment or use the module form.

For a live trial without manual key setup, run `flashdata-transcript auth trial`. Subsequent CLI and Python calls reuse the saved access. See the [live trial guide](live-trial.md) for claim, expiry, and interrupted-setup recovery.

Alternatively, set `FLASHDATA_API_KEY` in the same shell that runs Python. It takes precedence over saved access. `.env.example` documents the variable; the toolkit does not automatically load `.env` files. A Google API key is not a FlashData API key.

The API key needs permission for `youtube_transcript`. Language discovery additionally uses `youtube_metadata`. Check API key source permissions and the account's available credits in the FlashData console.

## Captions or language unavailable

- Check that the video is available and has captions.
- `auto=True` requests automatic captions; `auto=False` requests uploader-provided captions. The client does not silently switch origins.
- Discover codes with `client.languages(video)`; this makes a separate Metadata request.
- For multi-language requests, inspect both `result.tracks` and `result.errors`. A successful HTTP response does not mean every requested language exists.
- This toolkit does not generate new captions from audio or run a translation model.

## Handle errors in Python

```python
from flashdata import APIError, FlashDataError
from flashdata_transcript import ResponseError, RetrievalFailed, TranscriptClient

try:
    with TranscriptClient() as client:
        transcript = client.fetch("YOUR_VIDEO_ID", language="en")
except APIError as error:
    print("HTTP status:", error.status_code)
except RetrievalFailed as error:
    print("Check this job in the console:", error.job_id)
except (FlashDataError, ResponseError):
    print("Check console History before resubmitting a request with an unknown outcome.")
except ValueError as error:
    print("Invalid input:", error)
```

The official SDK's exceptions are preserved. Authentication, credits, and rate-limit errors should be addressed before another attempt. The client does not automatically retry realtime submissions.

Malformed responses raise `ResponseError` rather than silently dropping missing results, mismatched video IDs, or missing languages. If reporting a bug, include the SDK/toolkit versions and a redacted response shape; do not share API keys or account credentials.

## Interrupted collection

Keep the `.checkpoint.json` file and resume with the same inputs. See the [collection guide](collection.md) for failed/uncertain entries, explicit retries, and stale locks.

## Existing output path

The CLI refuses to overwrite existing files. Use a new filename, or use `--resume` for a collection. `convert` and `chunks` accept a single normalized transcript JSON file, not the multi-language result envelope.

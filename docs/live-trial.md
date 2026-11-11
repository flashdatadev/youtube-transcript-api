# Try real YouTube transcripts before signup

```bash
flashdata-transcript auth trial
flashdata-transcript fetch YOUR_VIDEO_ID --language en --output transcript.json
```

The first command initializes FlashData's existing [temporary-access protocol](https://flashdata.dev/auth.md). It provisions an eligible trial account and ordinary API key without asking you to supply a key. The second command makes a real request to the YouTube Transcript API.

The toolkit requests only `youtube_transcript` and `youtube_metadata`. Manual caption selection uses `auto=False` on the transcript source; language discovery uses metadata. No Google, media download, or unrelated source permissions are requested.

`auth trial` prints the connection ID, expiry, starting credit allowance, source request equivalents, and credential protection. Request equivalents are alternative uses of one balance; they are not separate quotas or remaining-request counters. The allowance comes from the service rather than a hardcoded promise.

## Existing access and repeated setup

Credential selection follows this order:

1. An explicit `TranscriptClient(api_key=...)` argument.
2. `FLASHDATA_API_KEY` in the environment.
3. The toolkit's saved trial or owner key.

`auth trial` reuses an environment key without creating a trial. It validates an existing saved connection instead of registering another one. An empty environment variable produces an error rather than switching accounts. To use saved access, unset that variable first.

Ordinary `TranscriptClient()` and `fetch` never create new trials automatically. Python programs can explicitly opt in:

```python
from flashdata_transcript import TranscriptClient

with TranscriptClient.from_trial() as client:
    transcript = client.fetch("YOUR_VIDEO_ID", language="en")
```

Expired, revoked, blocked, or exhausted access is not replaced with another trial. Supply an existing owner key, or claim an active trial as described below. Realtime transcript requests are not automatically retried after an uncertain outcome.

## Where credentials are stored

The default directory is `~/.flashdata-transcript`. You can choose an absolute private directory with `FLASHDATA_TRANSCRIPT_STATE_DIR`, or pass `--state-dir` to each online CLI command. Python supports `state_dir=...` on `TranscriptClient` and `from_trial()`.

Use the **same directory throughout setup, fetching, claiming, and finishing**. Do not create new directories to replenish trials.

- Windows: credential state is encrypted with the current user's DPAPI protection.
- macOS/Linux: the state directory uses mode `0700`, and state files use `0600`.
- Writes are atomic, and concurrent authentication commands are serialized by an OS lock.
- Keys and registration/handoff proofs are never printed or accepted in CLI arguments.

Keep state outside your repository. Copying Windows state to another user or machine will not decrypt it. On POSIX systems, protect backups as you would any credential file.

## Recover an interrupted setup

A random registration proof and immutable request body are saved **before** registration is sent. If the response is lost, run `auth trial` again with the same state directory. The server returns the original registration rather than granting another trial.

The client never deletes unreadable state or silently replaces its proof. A corrupt state file needs recovery from your protected backup or an existing owner key. It is not an invitation to create another trial.

## Connect an owner account

While the trial remains active:

```bash
flashdata-transcript auth claim
```

Open `claim_url` in your browser and enter `confirmation_code`. The code is shown separately and is not included in the URL. Sign in or sign up, verify your email if needed, and explicitly approve the selected source permissions and use of your shared account balance. This approval does not buy credits.

The command reuses an unexpired claim link. Browser approval is always your action; the toolkit never submits approval for you.

```bash
flashdata-transcript auth finish --wait --timeout 600
flashdata-transcript auth status
```

`finish` respects the service's polling interval. It saves the replacement owner key atomically, starts a fresh Python process to verify that the saved key can authenticate, and acknowledges installation. Obsolete trial proofs are then removed. A lost handoff or acknowledgement response can be recovered by running `auth finish` again with the same state directory.

Without `--wait`, `finish` checks once and exits with code `2` if browser approval is still pending. If a handoff is pending locally, normal fetching pauses until `finish` completes; it does not fall back to a revoked trial key.

After installation, normal API calls use the owner's shared balance. Unused temporary trial credits do not transfer. You can revoke the connection in [FlashData account settings](https://flashdata.dev/app/settings/connections).

## Offline demo remains separate

`flashdata-transcript demo` produces synthetic caption exports locally. It makes no requests, creates no trial, and writes no credentials. Use `auth trial` followed by `fetch` to evaluate live retrieval.

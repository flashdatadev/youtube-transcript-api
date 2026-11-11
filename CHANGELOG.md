# Changelog

## 0.2.0

- Live trial onboarding without manual signup or API key setup: `auth trial`.
- Automatic reuse of saved trial/owner keys in Python and CLI; explicit keys retain precedence.
- `TranscriptClient.from_trial()` for a Python-only live quickstart.
- Private, atomic credential storage with Windows DPAPI and POSIX file permissions.
- Registration recovery reuses the original proof and never silently renews trials.
- Browser account claiming and owner-key handoff with fresh-process verification.

## 0.1.0

- Python client and CLI on top of the official FlashData SDK.
- Automatic/uploader caption selection, language discovery, and multi-language results.
- JSON, text, SRT, WebVTT, CSV, and Markdown exports.
- Transcript chunks with language metadata and timestamped source links.
- Sequential JSONL collections with checkpoints and explicit failure recovery.
- Offline synthetic demo and runnable Python examples.

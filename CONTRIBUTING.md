# Contributing

Use Python 3.10 or newer. Fork and clone the repository, create a virtual environment, then install development dependencies:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m build
python -m twine check dist/*
```

Tests must run offline with synthetic transcript text and mocked HTTP. Exercise the real FlashData SDK request/response boundary when changing client behavior. Include tests for partial results, caption origin, and language identity when adding a new retrieval feature.

Keep CLI stdout machine-readable; put diagnostics on stderr. Preserve error records and checkpoint recovery. Do not add automatic retries for requests with an unknown submission outcome.

Check examples with `--help` and run `flashdata-transcript demo --output output/check-demo`. Do not commit API keys, `.env` files, generated outputs, or real customer transcripts.

Bug reports should include the command or minimal code, OS/Python/toolkit versions, expected behavior, and redacted error details. Proposed features should identify a concrete user workflow and the documented API capability that supports it.

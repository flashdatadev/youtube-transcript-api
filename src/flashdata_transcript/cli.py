"""Command-line transcript fetching, conversion, and collection."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path

from flashdata import APIError, FlashDataError

from . import __version__
from .chunks import chunk_transcript
from .client import TranscriptClient
from .collection import collect
from .demo import sample_transcript
from .errors import TranscriptError
from .formats import FORMATS, render
from .models import Transcript


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


@contextmanager
def _output(path: str | None):
    """Reserve the destination before any paid request; don't overwrite existing data."""
    if path is None:
        yield sys.stdout
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stream = destination.open("x", encoding="utf-8", newline="\n")
    try:
        yield stream
    except BaseException:
        stream.close()
        if destination.stat().st_size == 0:
            destination.unlink()
        raise
    finally:
        stream.close()


def _load(path: str) -> Transcript:
    return Transcript.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="YouTube Transcript API Toolkit by FlashData")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Fetch one existing caption track")
    fetch.add_argument("video", help="YouTube video ID or URL")
    fetch.add_argument("--language", default=None, help="Example: en, es, zh-Hans, en-orig")
    fetch.add_argument("--manual", action="store_true", help="Request uploader captions")
    fetch.add_argument("--format", choices=FORMATS, default="json")
    fetch.add_argument("--output", help="New output file; defaults to stdout")
    languages = commands.add_parser("languages", help="Discover language codes via Metadata")
    languages.add_argument("video")
    languages.add_argument("--output")
    multi = commands.add_parser("fetch-languages", help="Try every code; keep per-language errors")
    multi.add_argument("video")
    multi.add_argument("--languages", nargs="+", required=True)
    multi.add_argument("--manual", action="store_true")
    multi.add_argument("--output")
    convert = commands.add_parser("convert", help="Convert toolkit JSON locally")
    convert.add_argument("input")
    convert.add_argument("--format", choices=FORMATS, required=True)
    convert.add_argument("--output")
    chunks = commands.add_parser("chunks", help="Build local JSONL chunks with source timestamps")
    chunks.add_argument("input")
    chunks.add_argument("--max-chars", type=int, default=1200)
    chunks.add_argument("--output")
    collection = commands.add_parser("collect", help="Collect a video list into resumable JSONL")
    collection.add_argument("input", help="Text file: one video ID or URL per line")
    collection.add_argument("--output", required=True)
    collection.add_argument("--language", default="en")
    collection.add_argument("--manual", action="store_true")
    collection.add_argument("--limit", type=int, default=100)
    collection.add_argument("--resume", action="store_true")
    collection.add_argument("--retry-failed", action="store_true")
    collection.add_argument("--retry-uncertain", action="store_true")
    demo = commands.add_parser("demo", help="Generate synthetic example exports; no API key needed")
    demo.add_argument("--output", default="output/demo", help="New directory for demo files")
    return root


def _run(args: argparse.Namespace) -> int:
    if args.command == "demo":
        directory = Path(args.output)
        directory.mkdir(parents=True, exist_ok=False)
        transcript = sample_transcript()
        for format in FORMATS:
            (directory / f"transcript.{format}").write_text(
                render(transcript, format), encoding="utf-8"
            )
        chunks = chunk_transcript(transcript, max_chars=120)
        (directory / "chunks.jsonl").write_text(
            "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks),
            encoding="utf-8",
        )
        print(f"Created synthetic demo exports in {directory}", file=sys.stderr)
        return 0
    if args.command == "collect":
        lines = Path(args.input).read_text(encoding="utf-8-sig").splitlines()
        with TranscriptClient() as client:
            summary = collect(
                client,
                lines,
                args.output,
                language=args.language,
                auto=not args.manual,
                limit=args.limit,
                resume=args.resume,
                retry_failed=args.retry_failed,
                retry_uncertain=args.retry_uncertain,
            )
        print(_json(summary), file=sys.stderr, end="")
        return 2 if summary["failed"] or summary["uncertain"] else 0
    with _output(args.output) as output:
        if args.command == "convert":
            output.write(render(_load(args.input), args.format))
        elif args.command == "chunks":
            for chunk in chunk_transcript(_load(args.input), max_chars=args.max_chars):
                output.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        else:
            with TranscriptClient() as client:
                if args.command == "fetch":
                    transcript = client.fetch(
                        args.video, language=args.language, auto=not args.manual
                    )
                    output.write(render(transcript, args.format))
                elif args.command == "languages":
                    output.write(_json(client.languages(args.video)))
                else:
                    result = client.fetch_languages(
                        args.video, args.languages, auto=not args.manual
                    )
                    output.write(_json(result.to_dict()))
                    return 0 if result.ok else 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("Interrupted. Collection checkpoints can be resumed.", file=sys.stderr)
        return 130
    except APIError as exc:
        print(
            f"FlashData HTTP {exc.status_code}. Check your key, credits, and console History.",
            file=sys.stderr,
        )
        return 1
    except FlashDataError:
        print(
            "FlashData request failed. Check your API key and console History before retrying.",
            file=sys.stderr,
        )
        return 1
    except (TranscriptError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

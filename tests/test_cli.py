import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from flashdata_transcript.cli import main


def test_offline_demo_and_conversion(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FLASHDATA_API_KEY", raising=False)
    directory = tmp_path / "demo"
    assert main(["demo", "--output", str(directory)]) == 0
    assert {path.name for path in directory.iterdir()} == {
        "transcript.json",
        "transcript.txt",
        "transcript.srt",
        "transcript.vtt",
        "transcript.csv",
        "transcript.md",
        "chunks.jsonl",
    }
    transcript = json.loads((directory / "transcript.json").read_text(encoding="utf-8"))
    assert transcript["is_demo"] is True
    assert transcript["source_url"] is None
    output = tmp_path / "converted.srt"
    assert (
        main(
            [
                "convert",
                str(directory / "transcript.json"),
                "--format",
                "srt",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert "00:00:00,000 --> 00:00:03,200" in output.read_text(encoding="utf-8")
    assert main(["demo", "--output", str(directory)]) == 1
    assert "Created synthetic" in capsys.readouterr().err


def test_existing_output_checked_before_constructing_client(tmp_path, monkeypatch):
    output = tmp_path / "already.json"
    output.write_text("Keep this", encoding="utf-8")

    def forbidden():
        pytest.fail("Client must not be used when output already exists")

    monkeypatch.setattr("flashdata_transcript.cli.TranscriptClient", forbidden)
    assert main(["fetch", "DEMO0000001", "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "Keep this"


def test_failed_conversion_does_not_leave_empty_output(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text("{}", encoding="utf-8")
    output = tmp_path / "out.srt"
    assert main(["convert", str(source), "--format", "srt", "--output", str(output)]) == 1
    assert not output.exists()


def test_module_and_offline_example_are_runnable(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("FLASHDATA_API_KEY", None)
    demo = subprocess.run(
        [sys.executable, "-m", "flashdata_transcript", "demo", "--output", str(tmp_path / "demo")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "synthetic" in demo.stderr
    example = Path(__file__).resolve().parents[1] / "examples" / "transcript_to_rag.py"
    result = subprocess.run(
        [sys.executable, str(example), str(tmp_path / "demo" / "transcript.json")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout.splitlines()[0])["is_demo"] is True


@pytest.mark.parametrize("example", ["fetch_transcript", "multiple_languages", "export_subtitles"])
def test_live_examples_help_needs_no_key(example):
    path = Path(__file__).resolve().parents[1] / "examples" / f"{example}.py"
    result = subprocess.run([sys.executable, str(path), "--help"], capture_output=True, check=True)
    assert b"usage:" in result.stdout

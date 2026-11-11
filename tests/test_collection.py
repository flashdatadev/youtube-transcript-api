import json
from dataclasses import replace

import pytest
from flashdata import APIError, SubmissionUnknownError

from flashdata_transcript import CollectionStopped, LanguageError, TranscriptResult, collect
from flashdata_transcript.collection import read_videos
from flashdata_transcript.demo import sample_transcript


class FakeClient:
    def __init__(self, outcomes=None):
        self.calls = []
        self.outcomes = outcomes or {}

    def fetch_languages(self, video, languages, *, auto):
        self.calls.append(video)
        outcome = self.outcomes.get(video)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is not None:
            return outcome
        track = replace(
            sample_transcript(), video_id=video, language_code=languages[0], is_auto_generated=auto
        )
        return TranscriptResult(video, (track,), (), "job_test")


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_deduplicates_and_never_repeats_success_on_resume(tmp_path):
    output = tmp_path / "collection.jsonl"
    client = FakeClient()
    videos = ["DEMO0000001", "https://youtu.be/DEMO0000001", "DEMO0000002"]
    summary = collect(client, videos, output)
    assert summary == {"success": 2, "failed": 0, "uncertain": 0, "pending": 0}
    assert client.calls == ["DEMO0000001", "DEMO0000002"]
    collect(client, videos, output, resume=True, retry_failed=True, retry_uncertain=True)
    assert len(client.calls) == 2
    assert len(rows(output)) == 2


def test_whole_input_validated_before_any_request(tmp_path):
    client = FakeClient()
    with pytest.raises(ValueError):
        collect(client, ["DEMO0000001", "bad"], tmp_path / "data.jsonl")
    assert client.calls == []
    assert list(tmp_path.iterdir()) == []


def test_read_videos_never_silently_truncates():
    with pytest.raises(ValueError, match="limit"):
        read_videos(["DEMO0000001", "DEMO0000002"], limit=1)
    assert read_videos(["# comment", "", "DEMO0000001"]) == ["DEMO0000001"]


def test_unknown_submission_saved_and_not_retried_implicitly(tmp_path):
    output = tmp_path / "data.jsonl"
    videos = ["DEMO0000001", "DEMO0000002", "DEMO0000003"]
    client = FakeClient({"DEMO0000002": SubmissionUnknownError("lost response")})
    with pytest.raises(CollectionStopped):
        collect(client, videos, output)
    assert [row["status"] for row in rows(output)] == ["success", "uncertain", "pending"]
    client.outcomes = {}
    summary = collect(client, videos, output, resume=True)
    assert client.calls == ["DEMO0000001", "DEMO0000002", "DEMO0000003"]
    assert summary["uncertain"] == 1
    collect(client, videos, output, resume=True, retry_uncertain=True)
    assert client.calls[-1] == "DEMO0000002"
    assert all(row["status"] == "success" for row in rows(output))


def test_interrupted_inflight_request_is_uncertain_after_resume(tmp_path):
    output = tmp_path / "data.jsonl"
    videos = ["DEMO0000001", "DEMO0000002"]
    client = FakeClient({"DEMO0000001": KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        collect(client, videos, output)
    assert rows(output)[0]["status"] == "in_progress"
    client.outcomes = {}
    collect(client, videos, output, resume=True)
    assert client.calls == ["DEMO0000001", "DEMO0000002"]
    assert rows(output)[0]["status"] == "uncertain"


def test_known_language_failure_is_retained_and_retry_is_explicit(tmp_path):
    output = tmp_path / "data.jsonl"
    client = FakeClient(
        {
            "DEMO0000001": TranscriptResult(
                "DEMO0000001",
                (),
                (LanguageError("en", "language_unavailable", "Missing captions."),),
            )
        }
    )
    summary = collect(client, ["DEMO0000001"], output)
    assert summary["failed"] == 1
    assert rows(output)[0]["result"]["errors"][0]["code"] == "language_unavailable"
    collect(client, ["DEMO0000001"], output, resume=True)
    assert len(client.calls) == 1
    client.outcomes = {}
    assert collect(client, ["DEMO0000001"], output, resume=True, retry_failed=True)["success"] == 1


@pytest.mark.parametrize(
    "status,expected",
    [(401, "failed"), (402, "failed"), (429, "failed"), (500, "uncertain"), (408, "uncertain")],
)
def test_api_errors_stop_without_retry_or_exposing_response_body(tmp_path, status, expected):
    output = tmp_path / "data.jsonl"
    client = FakeClient({"DEMO0000001": APIError(status, "secret-key-in-server-message")})
    with pytest.raises(CollectionStopped):
        collect(client, ["DEMO0000001", "DEMO0000002"], output)
    assert len(client.calls) == 1
    assert rows(output)[0]["status"] == expected
    assert "secret-key" not in output.read_text(encoding="utf-8")


def test_resume_requires_same_inputs_and_preserves_existing_files(tmp_path):
    output = tmp_path / "data.jsonl"
    client = FakeClient()
    collect(client, ["DEMO0000001"], output)
    original = output.read_bytes()
    with pytest.raises(ValueError, match="same video list"):
        collect(client, ["DEMO0000001"], output, language="es", resume=True)
    with pytest.raises(FileExistsError):
        collect(client, ["DEMO0000001"], output)
    assert output.read_bytes() == original
    assert len(client.calls) == 1


def test_resume_regenerates_output_from_checkpoint_without_new_requests(tmp_path):
    output = tmp_path / "data.jsonl"
    client = FakeClient()
    collect(client, ["DEMO0000001"], output)
    output.write_text("interrupted output", encoding="utf-8")
    collect(client, ["DEMO0000001"], output, resume=True)
    assert rows(output)[0]["status"] == "success"
    assert len(client.calls) == 1


def test_lock_blocks_parallel_collectors(tmp_path):
    output = tmp_path / "data.jsonl"
    output.with_name("data.jsonl.lock").touch()
    client = FakeClient()
    with pytest.raises(ValueError, match="locked"):
        collect(client, ["DEMO0000001"], output)
    assert client.calls == []

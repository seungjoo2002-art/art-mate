"""GitHub Actions 일괄 Worker: CLI 옵션·처리 종류 선택·워크플로 설정 (DB 없음)."""

from pathlib import Path

import pytest
import yaml

from app.models.enums import AiJobType
from app.worker.__main__ import (
    parse_args,
    pending_outputs,
    supported_job_types,
    write_github_output,
)
from tests.conftest import make_settings

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "stt-worker.yml"


def test_parse_args() -> None:
    args = parse_args(["--once", "--max-jobs", "3", "--max-seconds", "60"])
    assert (args.once, args.max_jobs, args.max_seconds, args.no_maintenance) == (True, 3, 60, False)
    assert parse_args([]).once is False
    for bad in (["--max-jobs", "0"], ["--max-seconds", "-1"]):
        with pytest.raises(SystemExit):
            parse_args(bad)


def test_supported_job_types_follow_capabilities() -> None:
    settings = make_settings()
    assert supported_job_types(settings, has_stt=True, has_llm=False) == {AiJobType.TRANSCRIBE}
    assert supported_job_types(settings, has_stt=False, has_llm=True) == {AiJobType.SUMMARIZE}
    growth = make_settings(growth_ai_enabled=True)
    assert supported_job_types(growth, has_stt=True, has_llm=True) == set(AiJobType)
    assert supported_job_types(settings, has_stt=False, has_llm=False) == frozenset()


def test_pending_outputs(tmp_path: Path) -> None:
    outputs = pending_outputs({"TRANSCRIBE": 2, "SUMMARIZE": 1, "GROWTH_REPORT": 1})
    assert outputs == {"transcribe": 2, "llm": 2, "total": 4}
    assert pending_outputs({}) == {"transcribe": 0, "llm": 0, "total": 0}
    target = tmp_path / "out"
    write_github_output(str(target), outputs)
    assert target.read_text(encoding="utf-8").splitlines() == ["transcribe=2", "llm=2", "total=4"]


def test_workflow_guards_and_limits() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))  # PyYAML은 'on'을 True로 읽는다
    assert set(triggers) == {"workflow_dispatch", "schedule"}  # PR·push로는 실행되지 않음
    assert workflow["concurrency"] == {"group": "stt-worker", "cancel-in-progress": False}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["work"]
    assert job["if"] == "github.repository == 'seungjoo2002-art/art-mate'"
    assert job["timeout-minutes"] <= 60
    env = job["env"]
    assert (env["STT_MODEL"], env["STT_DEVICE"], env["STT_COMPUTE_TYPE"], env["STT_LANGUAGE"]) == (
        "small",
        "cpu",
        "int8",
        "ko",
    )
    assert env["DATABASE_URL"] == "${{ secrets.WORKER_DATABASE_URL }}"
    assert env["GEMINI_API_KEY"] == "${{ secrets.GEMINI_API_KEY }}"
    assert "false" in env["AI_SUMMARY_ENABLED"]  # 승인 전에는 Gemini 처리 꺼짐
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "service_role" not in text.lower() and "SUPABASE_ANON_KEY" not in text
    commands = " ".join(s.get("run", "") for s in job["steps"])
    assert "python -m app.worker --once" in commands and "--pending" in commands

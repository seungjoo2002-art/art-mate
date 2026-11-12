"""STT 비교 도구: 평가 지표(프론트와 같은 기준)와 외부 전송 차단."""

import argparse

import pytest

from app.services.stt_metrics import cer, term_accuracy
from scripts import stt_compare


def test_cer_ignores_spaces_and_punctuation() -> None:
    assert cer("명암을 더 줘.", "명암을더줘") == 0
    assert cer("명암을 더 줘", "명함을 더 줘") == pytest.approx(1 / 5)
    assert cer("", "x") is None


def test_term_accuracy_counts_occurrences() -> None:
    ref = "명암 대비가 약해. 명암을 다시 잡고 소실점을 맞춰."
    hyp = "명함 대비가 약해. 명암을 다시 잡고 소실점을 맞춰."
    result = term_accuracy(ref, hyp)
    assert (result.total, result.matched, result.missed) == (4, 3, ["명암"])
    assert result.ratio == 0.75
    assert term_accuracy("안녕", "안녕").ratio is None


def test_external_engines_need_explicit_approval(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk_test")

    def no_network(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("external STT must not be called without --allow-external")

    monkeypatch.setattr(stt_compare.httpx, "post", no_network)
    args = argparse.Namespace(allow_external=False, openai_model="gpt-4o-transcribe")
    for engine in stt_compare.EXTERNAL:
        assert "미승인" in stt_compare.build(engine, args)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    assert stt_compare.main([str(audio), "--engines", "groq-large-v3,openai-transcribe"]) == 0
    out = capsys.readouterr().out
    assert out.count("skipped: 외부 전송 미승인") == 2


def test_external_engine_without_key_is_skipped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    args = argparse.Namespace(allow_external=True, openai_model="gpt-4o-transcribe")
    assert stt_compare.build("groq-large-v3-turbo", args) == "GROQ_API_KEY 없음"

"""v0.9.8 단계별 사진 타임라인 · 피드백 기준 이미지 · AI 첨삭 데이터셋 기반.

- 타임라인: 한 단계에 여러 장, 사진과 피드백을 시각 순으로, 피드백 뒤 사진도 일반 사진과 같음
- 기준 이미지: 고르기·복수·제안(최신)·확인, 이후 사진이 추가돼도 고정, 다른 작품 사진 거부
- STT 전사·AI 요약이 같은 기준 이미지를 보여 줌
- 학습 활용 동의 (만 14세 미만 불가, 철회)
- 데이터셋: 동의·확인된 기준 이미지·강사 피드백만 샘플, 제외 사유, 가명 처리, 원문/레이블 분리
- 기존 데이터: 0014 → 0015 백필은 '제안'으로만, 사진·피드백 보존, downgrade 보존
"""

from __future__ import annotations

import uuid

import asyncpg
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.worker.runner import JobRunner
from tests.db.conftest import Actor
from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic
from tests.db.test_recordings_api import _consent, _record
from tests.db.test_v09_learning_cycle import Ai, _ai_consent, note_ai_json
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt
from tests.fake_storage import FakeStorage, image_bytes

API = "/api/v1"
NOTE = (
    "구도는 화면 중앙에 안정적으로 잘 잡았다. 오른쪽 컵의 명암이 너무 약해서 형태가 떠 보인다. "
    "어두운 면을 한 톤 더 눌러서 덩어리감을 살려라.\n시간 안에 배경까지 마무리하지 못했다."
)
DS_VERSION = "2026-11-ds-v1"


@pytest.fixture
def storage(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.storage


@pytest.fixture
def ai(app, client) -> Ai:  # type: ignore[no-untyped-def]
    stt, llm = FakeStt(), FakeLlm()
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=stt,
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="w-v098",
    )
    return Ai(runner, stt, llm)


_SEQ = iter(range(1, 100_000))


async def _artwork(client: httpx.AsyncClient, owner: Actor, **body) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks", json={"title": "타임라인 작품"} | body, headers=owner.headers
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _photo(client, storage: FakeStorage, owner: Actor, artwork_id: str, **body) -> dict:  # type: ignore[no-untyped-def]
    payload = image_bytes("PNG", color="blue", size=(20 + next(_SEQ), 20))
    ticket = await client.post(
        f"{API}/artworks/{artwork_id}/photos",
        json={"content_type": "image/png", "file_size": len(payload)} | body,
        headers=owner.headers,
    )
    assert ticket.status_code == 201, ticket.text
    storage.put(ticket.json()["upload"]["path"], payload)
    done = await client.post(
        f"{API}/artworks/{artwork_id}/photos/{ticket.json()['photo']['id']}/complete",
        headers=owner.headers,
    )
    assert done.status_code == 200, done.text
    return done.json()


async def _note(client, owner: Actor, artwork_id: str, **body) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks/{artwork_id}/feedback-notes",
        json={"source": "INSTRUCTOR", "body": NOTE} | body,
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


def _ref_ids(refs: dict) -> list[str]:
    return [p["photo_id"] for p in refs["photos"]]


async def _sql(app, sql: str, **params):  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return result.all() if result.returns_rows else []


# ============================================================ B. 단계별 사진 타임라인


async def test_stage_timeline_mixes_photos_and_feedback(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, storage
) -> None:
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    sketch, color, _ = artwork["stage_plan"]
    p1 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    p2 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    feedback1 = await _note(client, student, artwork["id"], stage_id=sketch["id"])
    p3 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    feedback2 = await _note(
        client, student, artwork["id"], stage_id=sketch["id"], body="오른쪽 그림자를 더 진하게."
    )
    overall = await _note(client, student, artwork["id"], body="전체적으로 톤이 밝다.")
    other = await _photo(client, storage, student, artwork["id"], stage_id=color["id"])

    # 한 단계에 여러 장, 피드백 뒤에 올린 사진도 같은 단계 사진 (별도 종류 없이)
    assert p3["kind"] == "STAGE" and p1["is_representative"] and not p2["is_representative"]
    detail = (await client.get(f"{API}/artworks/{artwork['id']}", headers=student.headers)).json()
    assert detail["photo_count"] == 4

    history = (
        await client.get(f"{API}/artworks/{artwork['id']}/stage-history", headers=student.headers)
    ).json()
    timeline = history["stages"][0]["timeline"]
    assert [(i["type"], (i["photo"] or i["feedback"])["id"]) for i in timeline] == [
        ("PHOTO", p1["id"]),
        ("PHOTO", p2["id"]),
        ("FEEDBACK", feedback1["id"]),
        ("PHOTO", p3["id"]),
        ("FEEDBACK", feedback2["id"]),
    ]
    assert [i["photo"]["id"] for i in history["stages"][1]["timeline"]] == [other["id"]]
    assert [f["id"] for f in history["overall_feedback"]] == [overall["id"]]

    # 피드백 뒤에 사진을 올리지 않아도 된다 (단계에 피드백만 있어도 정상)
    only_feedback = await _note(client, student, artwork["id"], stage_id=color["id"])
    history = (
        await client.get(f"{API}/artworks/{artwork['id']}/stage-history", headers=student.headers)
    ).json()
    assert history["stages"][1]["timeline"][-1]["feedback"]["id"] == only_feedback["id"]


async def test_many_photos_per_stage(client: httpx.AsyncClient, actors, storage, app) -> None:  # type: ignore[no-untyped-def]
    assert app.state.settings.artwork_max_photos_per_stage >= 10
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student, stages=[{"name": "한 단계"}])
    stage_id = artwork["stage_plan"][0]["id"]
    ids = [
        (await _photo(client, storage, student, artwork["id"], stage_id=stage_id))["id"]
        for _ in range(12)
    ]
    detail = (await client.get(f"{API}/artworks/{artwork['id']}", headers=student.headers)).json()
    assert {p["id"] for p in detail["photos"]} == set(ids)


# ============================================================ C. 피드백 기준 이미지


async def test_reference_images_select_suggest_confirm_and_freeze(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, storage, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    sketch, color, _ = artwork["stage_plan"]
    p1 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    p2 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    pc = await _photo(client, storage, student, artwork["id"], stage_id=color["id"])

    # 고르지 않으면 같은 단계의 최신 사진을 '제안' (확인 아님)
    suggested = await _note(client, student, artwork["id"], stage_id=sketch["id"])
    assert suggested["image_refs"]["status"] == "SUGGESTED"
    assert _ref_ids(suggested["image_refs"]) == [p2["id"]]
    # 작품 전체 피드백은 작품 전체의 최신 사진
    overall = await _note(client, student, artwork["id"], source="SELF_NOTE", body="전체 메모")
    assert _ref_ids(overall["image_refs"]) == [pc["id"]]

    # 여러 장을 골라 확인 (작품 전체 피드백은 여러 단계 사진 참조 가능)
    chosen = await _note(
        client,
        student,
        artwork["id"],
        reference_photo_ids=[p1["id"], pc["id"]],
        reference_confirmed=True,
    )
    assert chosen["image_refs"]["status"] == "CONFIRMED"
    assert _ref_ids(chosen["image_refs"]) == [p1["id"], pc["id"]]
    assert chosen["image_refs"]["confirmed_at"]

    # 이후 사진이 추가돼도 과거 피드백의 기준 이미지는 그대로
    await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    again = (
        await client.get(f"{API}/feedback-notes/{suggested['id']}", headers=student.headers)
    ).json()
    assert (
        _ref_ids(again["image_refs"]) == [p2["id"]] and again["image_refs"]["status"] == "SUGGESTED"
    )

    # 제안 확인·변경 (명시적 저장)
    confirmed = await client.put(
        f"{API}/feedback-notes/{suggested['id']}/image-refs",
        json={"photo_ids": [p1["id"]], "confirmed": True},
        headers=student.headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["image_refs"]["status"] == "CONFIRMED"
    assert _ref_ids(confirmed.json()["image_refs"]) == [p1["id"]]
    # 사진 없이 받은 피드백이라고 확인
    none = await client.put(
        f"{API}/feedback-notes/{overall['id']}/image-refs",
        json={"photo_ids": [], "confirmed": True},
        headers=student.headers,
    )
    assert none.json()["image_refs"]["status"] == "NONE"
    assert none.json()["image_refs"]["confirmed_at"] and none.json()["image_refs"]["photos"] == []

    # 거부: 다른 작품 사진, 없는 사진, 11장
    other = await _artwork(client, student)
    foreign = await _photo(
        client, storage, student, other["id"], stage_id=other["stage_plan"][0]["id"]
    )
    for ids, code in (
        ([foreign["id"]], 422),
        ([str(uuid.uuid4())], 422),
        ([p1["id"]] * 11, 422),
    ):
        assert (
            await client.put(
                f"{API}/feedback-notes/{suggested['id']}/image-refs",
                json={"photo_ids": ids, "confirmed": True},
                headers=student.headers,
            )
        ).status_code == code
    # 다른 학생은 바꿀 수 없다
    intruder = await actors.signup("STUDENT")
    assert (
        await client.put(
            f"{API}/feedback-notes/{suggested['id']}/image-refs",
            json={"photo_ids": [], "confirmed": True},
            headers=intruder.headers,
        )
    ).status_code == 404

    # 참조한 사진을 지워도 연결 기록은 남는다 (사진 상태로 표시)
    assert (
        await client.delete(
            f"{API}/artworks/{artwork['id']}/photos/{pc['id']}", headers=student.headers
        )
    ).status_code == 204
    kept = (
        await client.get(f"{API}/feedback-notes/{chosen['id']}", headers=student.headers)
    ).json()
    assert [(p["photo_id"], p["photo_status"]) for p in kept["image_refs"]["photos"]] == [
        (p1["id"], "ACTIVE"),
        (pc["id"], "DELETED"),
    ]


async def test_recording_refs_survive_stt_and_ai_summary(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, storage, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artwork = await _artwork(client, student, practical_type="DRAWING")
    sketch = artwork["stage_plan"][0]
    p1 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    p2 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])

    # 녹음: 녹음을 시작할 때 본 사진을 골라 확인
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(
        client,
        app.state.audio_storage,
        student,
        artwork["id"],
        stage_id=sketch["id"],
        reference_photo_ids=[p1["id"]],
        reference_confirmed=True,
    )
    assert recorded.status_code == 200, recorded.text
    recording = recorded.json()
    assert _ref_ids(recording["image_refs"]) == [p1["id"]]
    assert recording["image_refs"]["status"] == "CONFIRMED"
    base = f"{API}/artworks/{artwork['id']}/recordings/{recording['id']}"
    assert (await client.post(f"{base}/transcription", headers=student.headers)).status_code == 202
    assert await ai.drain() == 1
    listed = (
        await client.get(f"{API}/artworks/{artwork['id']}/recordings", headers=student.headers)
    ).json()
    assert _ref_ids(listed[0]["image_refs"]) == [p1["id"]]  # STT 후에도 그대로

    # 글 첨삭 → AI 요약: 요약 응답에 원본 피드백의 기준 이미지
    note = await _note(
        client,
        student,
        artwork["id"],
        stage_id=sketch["id"],
        reference_photo_ids=[p2["id"], p1["id"]],
        reference_confirmed=True,
    )
    assert (
        await client.post(f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers)
    ).status_code == 202
    ai.llm.outcomes.append(note_ai_json())
    assert await ai.drain() == 1
    current = (
        await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)
    ).json()
    feedback = (
        await client.get(f"{API}/feedbacks/{current['feedback_id']}", headers=student.headers)
    ).json()
    assert _ref_ids(feedback["image_refs"]) == [p2["id"], p1["id"]]
    assert feedback["image_refs"]["status"] == "CONFIRMED"
    # 기준 이미지를 바꿔도 AI 요약은 무효화되지 않고, 요약 응답도 새 연결을 따른다
    await client.put(
        f"{API}/feedback-notes/{note['id']}/image-refs",
        json={"photo_ids": [p1["id"]], "confirmed": True},
        headers=student.headers,
    )
    feedback = (
        await client.get(f"{API}/feedbacks/{current['feedback_id']}", headers=student.headers)
    ).json()
    assert feedback["status"] == "DRAFT" and _ref_ids(feedback["image_refs"]) == [p1["id"]]


# ============================================================ D. 학습 활용 동의 · 데이터셋


async def _ds_consent(client, student: Actor, birth: str = "2000-01") -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.post(
        f"{API}/dataset-consents/me",
        json={"policy_version": DS_VERSION, "agreed": True, "birth_year_month": birth},
        headers=student.headers,
    )


async def test_dataset_consent(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    status = (await client.get(f"{API}/dataset-consents/me", headers=student.headers)).json()
    assert status["is_valid"] is False and status["required_version"] == DS_VERSION
    granted = await _ds_consent(client, student)
    assert granted.status_code == 201 and granted.json()["age_band"] == "ADULT"
    child = await actors.signup("STUDENT")
    under = await _ds_consent(client, child, birth="2016-01")
    assert (
        under.status_code == 409 and under.json()["error"]["code"] == "DATASET_CONSENT_UNAVAILABLE"
    )
    wrong = await client.post(
        f"{API}/dataset-consents/me",
        json={"policy_version": "old", "agreed": True, "birth_year_month": "2000-01"},
        headers=student.headers,
    )
    assert wrong.status_code == 409
    assert (
        await client.delete(f"{API}/dataset-consents/me", headers=student.headers)
    ).status_code == 204
    assert (await client.get(f"{API}/dataset-consents/me", headers=student.headers)).json()[
        "is_valid"
    ] is False


async def test_dataset_samples_only_consented_confirmed_instructor_feedback(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, storage
) -> None:
    admin = await actors.admin()
    student = await actors.signup("STUDENT")
    assert (await _ds_consent(client, student)).status_code == 201
    artwork = await _artwork(
        client, student, practical_type="DRAWING", topic="유리컵", exam_materials="유리컵, 사과 2개"
    )
    sketch = artwork["stage_plan"][0]
    photo = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    good = await _note(
        client,
        student,
        artwork["id"],
        stage_id=sketch["id"],
        reference_photo_ids=[photo["id"]],
        reference_confirmed=True,
    )
    suggested = await _note(client, student, artwork["id"], stage_id=sketch["id"])
    self_note = await _note(
        client,
        student,
        artwork["id"],
        source="SELF_NOTE",
        body="내 메모",
        reference_photo_ids=[photo["id"]],
        reference_confirmed=True,
    )
    # 동의하지 않은 학생의 확인된 강사 첨삭
    other = await actors.signup("STUDENT")
    other_art = await _artwork(client, other)
    other_photo = await _photo(
        client, storage, other, other_art["id"], stage_id=other_art["stage_plan"][0]["id"]
    )
    no_consent = await _note(
        client,
        other,
        other_art["id"],
        reference_photo_ids=[other_photo["id"]],
        reference_confirmed=True,
    )
    # 전문가 레이블 (원문과 분리 저장, 확인됨)
    await _sql(
        app,
        "INSERT INTO feedback_labels (id, artwork_id, owner_id, feedback_note_id, origin,"
        " verification, problem_type, target_object, photo_id, region, description,"
        " recommendation, severity, evidence_segment_ids, verified_by, verified_at)"
        " VALUES (:id, :a, :o, :n, 'EXPERT', 'CONFIRMED', 'VALUE', '오른쪽 컵', :p,"
        " CAST(:region AS jsonb), '컵의 명암이 약함', '어두운 면을 한 톤 더', 3, '{1}', :o, now())",
        id=uuid.uuid4(),
        a=artwork["id"],
        o=student.user_id,
        n=good["id"],
        p=photo["id"],
        region='{"x": 0.6, "y": 0.4, "w": 0.2, "h": 0.3}',
    )

    # 학생·강사는 볼 수 없다
    assert (
        await client.get(f"{API}/admin/dataset/stats", headers=student.headers)
    ).status_code == 403
    stats = (await client.get(f"{API}/admin/dataset/stats", headers=admin.headers)).json()
    assert stats["eligible"] >= 1
    for reason in (
        "IMAGE_REF_NOT_CONFIRMED",
        "NOT_INSTRUCTOR_FEEDBACK",
        "NO_DATASET_CONSENT",
    ):
        assert stats["excluded"].get(reason, 0) >= 1

    # 가명 처리 키가 없으면 샘플 내보내기는 꺼져 있다
    disabled = await client.get(f"{API}/admin/dataset/samples", headers=admin.headers)
    assert disabled.status_code == 503
    app.state.settings.dataset_pseudonym_key = SecretStr("test-key")
    try:
        samples = (
            await client.get(f"{API}/admin/dataset/samples?limit=500", headers=admin.headers)
        ).json()
    finally:
        app.state.settings.dataset_pseudonym_key = None
    by_id = {s["sample_id"]: s for s in samples}
    assert good["id"] in by_id
    for excluded in (suggested["id"], self_note["id"], no_consent["id"]):
        assert excluded not in by_id
    sample = by_id[good["id"]]
    assert sample["learner"] != student.user_id and len(sample["learner"]) == 24
    assert [i["photo_id"] for i in sample["images"]] == [photo["id"]]
    assert sample["images"][0]["stage_name"] == "스케치" and sample["feedback_stage"] == "스케치"
    assert (sample["practical_type"], sample["topic"], sample["exam_materials"]) == (
        "DRAWING",
        "유리컵",
        "유리컵, 사과 2개",
    )
    assert sample["raw_text"] == NOTE and sample["transcript"] is None
    assert sample["expert_verified"] is False  # 강사가 AI 요약을 확정하지 않음
    expert = [lab for lab in sample["labels"] if lab["origin"] == "EXPERT"]
    assert expert and expert[0]["verification"] == "CONFIRMED"
    assert expert[0]["region"] == {"x": 0.6, "y": 0.4, "w": 0.2, "h": 0.3}
    assert sample["consent_version"] == DS_VERSION

    # 동의를 철회하면 즉시 빠진다
    await client.delete(f"{API}/dataset-consents/me", headers=student.headers)
    app.state.settings.dataset_pseudonym_key = SecretStr("test-key")
    try:
        samples = (
            await client.get(f"{API}/admin/dataset/samples?limit=500", headers=admin.headers)
        ).json()
    finally:
        app.state.settings.dataset_pseudonym_key = None
    assert good["id"] not in {s["sample_id"] for s in samples}


# ============================================================ 기존 데이터 (0014 → 0015)


async def test_0015_backfills_suggestions_only_and_keeps_data(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    user, artwork, stage = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    early, late, revision = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    note_after, note_before = uuid.uuid4(), uuid.uuid4()
    try:
        _alembic("downgrade", "0014")
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, '학생', 'STUDENT')",
            user,
        )
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, title, work_date)"
            " VALUES ($1, $2, '기존 작품', current_date)",
            artwork,
            user,
        )
        await conn.execute(
            "INSERT INTO artwork_stages (id, artwork_id, owner_id, position, name, legacy_stage)"
            " VALUES ($1, $2, $3, 0, '스케치', 'FINAL')",
            stage,
            artwork,
            user,
        )
        for i, (photo, minutes, kind, rep) in enumerate(
            (
                (early, 60, "STAGE", True),
                (late, 30, "STAGE", False),
                (revision, 10, "REVISION", False),
            )
        ):
            await conn.execute(
                "INSERT INTO artwork_photos (id, artwork_id, owner_id, stage, stage_id, kind,"
                " status, storage_path, content_type, size_bytes, width, height, sha256,"
                " upload_expires_at, uploaded_at, is_representative) VALUES ($1, $2, $3, 'FINAL',"
                " $4, $5, 'ACTIVE', $6, 'image/png', 1, 1, 1, $7, now(),"
                " now() - make_interval(mins => $8), $9)",
                photo,
                artwork,
                user,
                stage,
                kind,
                f"{user}/{artwork}/{i}.png",
                photo.hex * 2,
                minutes,
                rep,
            )
        segments = '[{"index": 0, "text": "메모"}]'
        for note, minutes in ((note_after, 20), (note_before, 120)):
            await conn.execute(
                "INSERT INTO feedback_notes (id, artwork_id, owner_id, stage_id, source, body,"
                " segments, segment_count, feedback_date, created_at)"
                " VALUES ($1, $2, $3, $4, 'INSTRUCTOR', '메모', $5, 1, current_date,"
                " now() - make_interval(mins => $6))",
                note,
                artwork,
                user,
                stage,
                segments,
                minutes,
            )

        _alembic("upgrade", "0015")
        # 피드백 시점 이전의 최신 사진을 '제안'으로만 (확인 아님)
        refs = await conn.fetch(
            "SELECT feedback_note_id, photo_id FROM feedback_image_refs WHERE artwork_id = $1",
            artwork,
        )
        assert {(r["feedback_note_id"], r["photo_id"]) for r in refs} == {(note_after, late)}
        statuses = dict(
            await conn.fetch(
                "SELECT id, image_ref_status FROM feedback_notes WHERE artwork_id = $1", artwork
            )
        )
        assert statuses == {note_after: "SUGGESTED", note_before: "NONE"}
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM artwork_photos WHERE artwork_id = $1", artwork
            )
            == 3
        )
        # 피드백 뒤 사진도 대표 가능
        await conn.execute(
            "UPDATE artwork_photos SET is_representative = (id = $1) WHERE artwork_id = $2",
            revision,
            artwork,
        )
        # 다른 작품 사진은 기준 이미지로 연결할 수 없다 (복합 FK)
        other_artwork = uuid.uuid4()
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, title, work_date)"
            " VALUES ($1, $2, '다른 작품', current_date)",
            other_artwork,
            user,
        )
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO feedback_image_refs (id, artwork_id, owner_id, feedback_note_id,"
                " photo_id, position) VALUES (gen_random_uuid(), $1, $2, $3, $4, 1)",
                other_artwork,
                user,
                note_after,
                early,  # 아직 연결되지 않은 사진 (유니크가 아니라 복합 FK로 거부되는지)
            )

        _alembic("downgrade", "0014")
        rows = await conn.fetch(
            "SELECT id, kind, is_representative FROM artwork_photos WHERE artwork_id = $1", artwork
        )
        assert len(rows) == 3  # 사진 보존
        assert all(not r["is_representative"] for r in rows if r["kind"] == "REVISION")
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM feedback_notes WHERE artwork_id = $1", artwork
            )
            == 2
        )
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
    finally:
        _alembic("upgrade", "head")
        await conn.execute("DELETE FROM profiles WHERE id = $1", user)
        await conn.close()

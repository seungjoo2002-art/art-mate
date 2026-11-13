# v0.9.7 사용자 정의 작품 단계 · 단계별 피드백 · 피드백 반영 수정 사진

## 무엇이 바뀌나

| 기능 | 이전 | v0.9.7 |
|---|---|---|
| 작품 단계 | 스케치 · 중간 작업 · 완성 고정 (시험 단계는 이 기기 localStorage) | 작품마다 1~10개, 이름 1~30자, 추가·삭제·이름·순서 변경. 새 작품 기본값 스케치 · 채색 · 완성 |
| 시험 모드 | 아이디어 · 스케치 · 채색 · 마무리 (VER.2 서버 시험 계획) | 단계 이름을 학생이 정함(1~4개) + 단계별 목표 시간. 진행·단계별 시간은 VER.2 서버 시험 계획(`/exam`) 그대로, 시험 단계 i = 작품 단계 i로 대응해 사진·메모·녹음이 그 단계에 연결 |
| 피드백 | 작품 단위 (녹음·글 첨삭) | 단계 피드백 또는 작품 전체 피드백. 나중에 단계 변경 가능 |
| 피드백 전후 사진 | 사진 교체만 | 단계 사진(피드백 전) → 피드백 → **수정 사진**(피드백 1개에 연결, 여러 장) |

수정 사진이 피드백을 잘 반영했는지는 **판단하지 않는다** (AI 판정 없음). 어떤 피드백 뒤에 올린 사진인지와 개수만 보여 준다.

## 데이터 모델 (마이그레이션 0014)

- `artwork_stages` (신규, RLS on): `artwork_id`, `owner_id`, `position`, `name`, `legacy_stage`, `target_minutes`, `archived_at`
  - 활성 단계 위치는 작품 안에서 유일 (`archived_at IS NULL` 부분 유니크)
  - `(id, artwork_id)` 유니크 → 사진·녹음·글 첨삭은 **같은 작품의 단계에만** 연결 (복합 FK)
- `artwork_photos`: `stage_id` (NOT NULL), `kind` STAGE/REVISION, `feedback_note_id` / `feedback_recording_id` (피드백 삭제 시 SET NULL → 사진은 보존)
  - 수정 사진은 대표 사진이 될 수 없음, 단계 사진은 피드백에 연결하지 않음, 피드백 참조는 최대 1개 (CHECK)
  - 대표 사진 유니크: `(artwork_id, stage)` → `(stage_id)`
- `feedback_recordings`, `feedback_notes`: `stage_id` NULL 허용 (NULL = 작품 전체 피드백)
- `legacy_stage` / 사진의 `stage`는 호환 값: 첫 단계 SKETCH, 마지막 단계 FINAL, 나머지 PROGRESS (단계 1개면 FINAL).
  진행도, "마지막 단계 사진이 있어야 작품 완료", 커뮤니티 공유 조건이 그대로 동작한다.

### 기존 데이터

- 기존 작품마다 단계 3개(스케치 / 중간 작업 / 완성 — 화면에 보이던 이름)를 만들고 기존 사진을 같은 단계로 옮긴다. 사진·녹음·글 첨삭 삭제 없음.
- 기존 피드백은 모두 작품 전체 피드백으로 남는다.
- downgrade: 새 컬럼·테이블 삭제, 대표 사진 유니크를 되돌림. 수정 사진은 일반 사진으로 남는다.

### 단계 삭제 = 숨김

단계 목록에서 뺀 단계에 사진(상태 무관)·녹음(삭제 포함)·글 첨삭이 하나라도 있으면 지우지 않고 `archived_at`만 기록한다.
숨긴 단계의 사진은 작품 상세·진행도·공유에서 빠지지만 `stage-history`와 `GET /stages`에는 남고, id를 다시 넣으면 복원된다.
데이터가 없는 단계만 실제로 지운다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/artworks` | `stages: [{ name, target_minutes? }]` (생략 시 기본 3단계). 시험 모드에서 제한 시간을 안 보내면 목표 시간 합 |
| GET | `/artworks/{id}` | `stage_plan` (활성 단계), 사진에 `stage_id`, `kind`, 피드백 참조 |
| GET | `/artworks/{id}/stages` | 활성 단계 순서대로 + 숨긴 단계 (`archived=true`) |
| PUT | `/artworks/{id}/stages` | 전체 목록을 순서대로 (`id` 있으면 기존 단계). 응답 `archived_stage_ids`, `deleted_stage_ids` |
| GET | `/artworks/{id}/stage-history` | 단계별 [사진 → 피드백 → 피드백별 수정 사진], 연결이 끊긴 수정 사진, `overall_feedback` |
| POST | `/artworks/{id}/photos` | `stage_id` (예전 `stage`도 허용), `kind`, `feedback_note_id` / `feedback_recording_id` |
| POST | `/artworks/{id}/recordings` | `stage_id` (선택) |
| PATCH | `/artworks/{id}/recordings/{rid}` | `{ stage_id }` (null = 작품 전체) |
| POST/PATCH | `/artworks/{id}/feedback-notes`, `/feedback-notes/{nid}` | `stage_id` (PATCH에서 null = 작품 전체, AI 요약은 무효화하지 않음) |
| GET | `/feedbacks/{id}`, `/artworks/{id}/feedbacks` | `stage_id`, `stage_name` |

규칙: 단계 피드백의 수정 사진은 같은 단계에만, 작품 전체 피드백의 수정 사진은 아무 단계에나.
수정 사진이 다른 단계에 있는 피드백을 그 단계로 옮기는 것은 거부(422), 작품 전체로 바꾸는 것은 허용.
수정 사진 상한: 단계당 `ARTWORK_MAX_REVISION_PHOTOS_PER_STAGE` (기본 20, 단계 사진 상한과 별도).

## 화면

- 새 작품 / 실기시험 준비 / 작품 정보 수정: 단계 편집기 (추가 · 삭제 · 이름 · 위아래 이동). 실기시험 준비는 최대 4단계 + 10분 단위 목표 시간(기본값은 계정의 시험 기본 목표, 시작 시 `/exam/plan` 저장). 작품 정보 수정은 이름·순서·개수만 (시험 목표 시간은 시험 계획이 관리). 숨긴 단계는 수정 화면에서 "다시 추가".
- VER.2 추가 사진(대표가 아닌 단계 사진)은 그 단계 묶음 안에서 피드백과 함께 올린 시각 순으로, "사진 추가"는 작품 단계 중에서 고른다. 커뮤니티 공유는 사진 1장부터.
- 작품 상세: 단계마다 [단계 사진 카드 → 그 단계 피드백(녹음·글) → 피드백별 "반영 후 사진 올리기"] → 맨 아래 작품 전체 피드백. 녹음 카드에서 연결 단계 변경.
- 녹음 / 글 첨삭 화면: "어느 단계의 피드백인가요?" (작품 상세의 단계에서 들어오면 미리 선택).
- 시험 진행·결과: 서버 시험 진행(VER.2) 그대로, 단계 이름은 작품 단계 이름. 단계 사진·메모·녹음이 그 단계에 연결 (단계 수가 다르면 예전 방식으로 대응).
- AI 정리 결과: "○○ 단계 피드백 / 작품 전체 피드백" 표시.

## 운영 적용 (승인 후)

1. 운영 DB 백업 확인 → `alembic upgrade 0014` (현재 운영 0013). **이 PR은 운영 DB에 적용하지 않았다.**
2. 백엔드 배포(Render) 후 프론트엔드 배포(Vercel). 0014 적용 전 새 백엔드를 배포하면 안 된다 (새 컬럼 필요).
3. 예전 프론트엔드는 `stage`(SKETCH/PROGRESS/FINAL)로 업로드해도 동작한다 (위치로 단계 매핑).

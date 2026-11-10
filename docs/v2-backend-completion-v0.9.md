# v0.9 기능명세서 V2 1~2단계 백엔드 완성 — 설계와 운영

> 작성: 2026-11-10 · 브랜치 `feature/v0.9-v2-backend-completion` · 리비전 `0009` (down_revision `0008`)
> 프론트 연동: [frontend-integration-v0.9.md](frontend-integration-v0.9.md) · DB: [database-design.md §3.23](database-design.md)

목표: **학생이 강사 계정·학원 가입 없이** 학습 목표 → 작품·시간 기록 → 음성/텍스트 첨삭 → AI 요약·분류 →
본인 확정 → 성장 아카이브 → 성장 리포트 → 맞춤 과제 → 수행 작품 → 후속 분석 → 알림까지 쓸 수 있게 한다.
기존 학원·강사 기능과 API는 유지한다 (응답 필드 추가, 일부 필드 NULL 허용만).

구현하지 않음: 실제 입시 정보 API·합격 예측, AI 사진 평가, 푸시·이메일 알림, 학습용 데이터 수집, 유료 STT.

## 1. 기능별 구현 (F-1~F-9)

| 기능 | 구현 | 기존 재사용 |
| --- | --- | --- |
| F-1 프로필·학습 목표 | `profiles.grade/learning_goal/learning_goal_updated_at`, `target_universities`(1:N, 우선순위, DEFERRABLE 유니크), 학습 맥락 API | `/users/me` |
| F-2 작품·제작 과정 | `artworks.topic/work_method/actual_minutes/time_limit_minutes/time_source`, 타이머 이벤트 `artwork_timer_events` | 단계별 사진 (v0.4), work_category=MOCK_EXAM |
| F-3 음성·텍스트 첨삭 | `feedback_notes`(출처 INSTRUCTOR/SELF_NOTE/PEER, 문장 segments), STT 결과 수정(새 전사 행), 강사 고지 상태, 음성 보관 기간 | 녹음·STT·작업 큐 (v0.5·v0.6) |
| F-4 AI 요약·분류 | 텍스트도 같은 SUMMARIZE 작업·출력 스키마, `TIME_MANAGEMENT` 카테고리, 근거 대조(2-gram), 근거 원문 문장 제공 | Gemini 요약·검토·이력 (v0.6) |
| F-5 성장 아카이브 | 작품 비교 API, 약점별 과거 첨삭 API, 타임라인에 시간·출처·과제 연결 | 타임라인 (v0.7) |
| F-6 커뮤니티 | 게시물 질문, 댓글 GENERAL/FEEDBACK + 항목, 피드백 채택 → PEER 첨삭 | 게시물·댓글·신고 (v0.8) |
| F-7 성장 리포트 | 학습 시간·모의시험 통계, 기간별 활동, 출처별 집계·참고 언급, 신규 사용자 안내 (`growth-v2`) | 규칙 기반 분석·리포트·AI 설명문 (v0.7) |
| F-8 맞춤 과제 | 시작(`started_at`), 학습 목표 문장, 수행 작품 연결 `practice_recommendation_artworks`, 후속 분석 | 추천·채택·완료 (v0.7), 학원 배포는 tasks 유지 |
| F-9 알림 | `notifications`(중복 방지 키), `notification_preferences`, 생성 훅, 정기 안내(Worker + 조회 시 계산) | Worker 루프 |

## 2. 핵심 설계 결정

### 2.1 텍스트 첨삭을 녹음 첨삭과 같은 파이프라인으로

- `feedback_summaries`에 `note_id`를 추가하고 `recording_id`·`transcript_id`를 NULL 허용으로 바꿨다.
  CHECK `one_source`: (녹음+전사) 또는 (텍스트) 중 정확히 하나. 기존 행은 모두 녹음이므로 영향 없음.
- 원문은 문장 단위 `segments [{index, text}]`로 저장한다 → AI 항목의 `evidence`(구간 번호)가 녹음과 같은 방식으로
  원문을 가리킨다. 항목·카테고리·검토 이력 테이블과 검토 API는 그대로 쓴다.
- 작업 큐 `ai_processing_jobs.note_id` + CHECK `summarize_has_source`, 진행 중 텍스트 작업 부분 유니크
  (`uq_ai_processing_jobs_active_note`)로 중복 요청을 막는다. 작업에 원문 version을 넣어 두고, 원문이 바뀌면
  Worker가 저장하지 않는다(`NOTE_CHANGED`). 원문 수정·전사 수정 시 진행 중 요약 작업은 취소한다.
- 외부 전송: 문장 번호와 문장만. 출처·이름·작품 제목·학원·ID는 보내지 않는다.

### 2.2 출처와 신뢰도

| 출처 | 확정 | 반복 약점·추세·근거 | 강사 화면 |
| --- | --- | --- | --- |
| INSTRUCTOR (녹음, 받아 적은 강사 첨삭) | 개인 작품: 학생 / 학원 작품: 담당 강사 | **포함** | 학원 작품이면 보임 |
| SELF_NOTE (자기 메모) | 학생 | 제외 → `unverified_mentions` 참고 | 보이지 않음 |
| PEER (다른 학생 의견, 커뮤니티 채택) | 학생 | 제외 → 참고 | 보이지 않음 |

- 학생이 받아 적은 "강사 첨삭"은 학생 기록이지만 v0.6과 같은 신뢰 수준(INSTRUCTOR)으로 본다. 학원 작품이면
  기존대로 담당 강사가 확정하므로 학원 흐름의 승인 구조가 유지된다. 개인 작품은 학생이 확정한다 (명세 요구).
- 커뮤니티 피드백은 채택 전에는 어떤 분석에도 쓰지 않는다. 채택해도 PEER라 반복 약점 통계에는 들어가지 않는다.

### 2.3 시간 기록 (exams API를 되살리지 않음)

- v0.5.1에서 제거한 `exam_*` 테이블·API는 학원 시험 세션 중심이라 개인 연습에 맞지 않는다. 작품(`artworks`)에
  실제 소요 시간·제한 시간 컬럼을 두고, 타이머는 append-only 이벤트로 기록한다. 상태·누적 시간은 조회 시
  이벤트를 재생해 계산하므로 서버에 장시간 프로세스가 없고, 새로고침·앱 종료 후에도 복원된다.
- 검증: 0·음수·1440분 초과 거부(DB CHECK + 스키마), 타이머 상태 전이, 이벤트 시각 범위(직전 이후·미래 2분 이내·
  24시간 이내), 24시간 초과 세션 거부. 제한 시간 초과는 저장하되 `over_time_limit`로 표시한다.

### 2.4 STT

- 기존 faster-whisper `small` · CPU INT8 · 한국어 · 비동기 큐 · 길이·크기 제한 · 재시도 · 중복 방지 유지.
- 결과 수정: 구간 수·시각은 그대로 두고 문장만 바꾼 **새 전사 행**을 만든다 (`edited_from_id`, `edited_by`).
  원본 보존, 확정된 첨삭이 있으면 잠금. 변환 실패 시 녹음 원본은 그대로 남는다 (기존).
- 정확도 측정 절차: §6.

### 2.5 개인정보·녹음 정책

- 녹음 업로드 시 강사 고지 확인(기존 `speaker_notice_confirmed`) + `speaker_consent_status`(NOTICE_GIVEN /
  CONSENT_REPORTED) 기록. 응답 `speaker_consent_verified=false` 고정 — 학생 기록이 강사의 법적 동의를 대신하지 않는다.
- 음성 원본 보관 기간 `RECORDING_AUDIO_RETENTION_DAYS`(기본 180일, 0=무기한): 지나면 음성 파일만 삭제
  (`audio_deleted_at`), 전사·첨삭은 학생이 지울 때까지 유지. service_role 키가 없으므로 Worker는 DB 표시만 하고,
  파일 삭제는 학생이 녹음 목록을 열 때 학생 토큰으로 수행한다 (기존 `storage_cleanup_pending` 경로).
- 학습 목적 데이터와 AI 모델 개발용 데이터 분리: 모델 학습 수집 기능·동의 목적이 없다 (`/meta/options`
  `data_policy.model_training_data_collection=false`). AI 전송 동의는 요약·성장 분석 목적만 (v0.6·v0.7).

### 2.6 알림

- 생성 훅(같은 트랜잭션): 리포트 생성, 개인 추천 묶음 생성(규칙·AI Worker), 학원 과제 배포.
- 정기 안내: Worker `maintenance()`(기본 1시간, `WORKER_MAINTENANCE_SECONDS`)와 사용자의 알림 목록 조회 시
  그 사용자만 계산 → Worker가 멈춰도 동작한다.
- 중복 방지: `(user_id, dedupe_key)` 유니크 + ON CONFLICT DO NOTHING. 미완료 과제는 과제당 주 1회·최대 3회,
  한 번 계산에 최대 3건. 목표 확인은 월 1회, 가입 7일 이후. 숨긴 알림도 행이 남아 다시 생기지 않는다.

## 3. 권한 요약

- 학생 본인: 프로필·지망 대학·작품·타이머·텍스트 첨삭·전사 수정·과제 연결·알림 (다른 사람 것은 404).
- 담당 강사: 기존 범위 + 학원 작품의 강사 첨삭(텍스트 포함) 검토. 자기 메모·PEER는 강사 API·대기열·성장 통계에서 제외.
- 작품 비교·약점별 과거 첨삭·후속 분석은 학생 API만 (강사 화면은 기존 성장 API).

## 4. 테스트

- DB 테스트: `tests/db/test_v09_learning_cycle.py`(F-1~F-5·F-7, 학원 작품 확정 규칙, 전사 수정·보관 기간),
  `tests/db/test_v09_tasks_community_notifications.py`(F-6·F-8·F-9, Worker 정기 작업),
  `tests/db/test_migrations_v09.py`(RLS·제약·왕복). 단위: `tests/test_v09_units.py`.
- 외부 STT·Gemini는 가짜 구현만 사용. 실제 호출 테스트는 없음 (승인 후 §6 절차로 별도 수행).
- 기존 테스트 변경: 근거(evidence)에 원문 `text` 추가, 요약 프롬프트 버전 `feedback-summary-v2` (2곳 기대값 갱신).

## 5. 운영·배포 (승인 필요)

1. Supabase 개발 DB: 현재 `0004` → `0005`~`0009` 순서대로 (승인 후). 0008 이후 `storage-setup.sql` v0.8 블록.
   0009는 Storage 정책 변경 없음.
2. 환경 변수(선택): `RECORDING_AUDIO_RETENTION_DAYS`(기본 180), `WORKER_MAINTENANCE_SECONDS`(기본 3600).
3. Worker 재배포 필요 (텍스트 요약·정기 작업). API와 같은 이미지.
4. 기존 리포트는 `growth-v1`으로 남고 새 필드는 기본값 → 학생이 재생성하면 `growth-v2`.

## 6. 실제 연동 검증 절차 (미수행, 승인 필요)

| 항목 | 절차 | 상태 |
| --- | --- | --- |
| Supabase Auth·Storage | 개발 DB 마이그레이션 → anon key 설정 → 사진·녹음 업로드·Signed URL·삭제 | 미수행 (anon key 없음, 개발 DB 0004) |
| STT 정확도 | 동의받은 실제 학원 녹음 10~20개(5~20분)를 `small`/int8로 전사, 사람이 고친 전사(PUT …/transcript 결과)와 CER 비교, `processing_ms`/녹음 길이 비율 기록 | 미수행 (실제 녹음 데이터 없음) |
| Gemini | 승인 후 소량(텍스트 첨삭 5건·녹음 2건) 호출 → 스키마 통과율·`dropped_item_count`·토큰 비용 확인 | 미수행 (유료 호출 미승인) |
| Render Worker | 배포 후 큐 처리·`maintenance done` 로그·메모리(STT 모델) 확인 | 미수행 |

## 7. 남은 위험·후속 과제

1. 근거 대조는 표면(2-gram) 비교라 말을 바꿔 쓴 정상 항목을 버리거나 비슷한 표현의 잘못된 항목을 통과시킬 수 있다 → 실제 데이터로 임계값 조정.
2. 학생이 받아 적은 "강사 첨삭"(INSTRUCTOR 텍스트)은 실제 강사 발언인지 확인할 수 없다 (개인 작품). 리포트 문구는 "기록된 첨삭" 기준.
3. 보관 기간이 지난 음성 파일은 학생이 앱을 열어야 실제 삭제된다 (service_role 미사용). 장기 미접속 사용자 처리 정책 필요.
4. 미성년자·강사 녹음 동의, 커뮤니티 채택 의견의 저작권·출처 표시는 법적 검토 필요 (v0.8 항목 유지).
5. 알림은 앱 내부만 (푸시 없음). 대상이 많아지면 `sweep_all` 배치 크기(500)·주기 조정 필요.

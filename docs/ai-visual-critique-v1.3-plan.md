# AI 시각적 첨삭 (v1.3) — 1단계 구조 분석·개발 계획

> 브랜치 `feature/ai-visual-critique` (최신 main `2cea59c`, PR #91 병합 후). 유료 API 호출 없음.
> 이 문서는 구현 전 승인용 계획이다. 확정되면 구현 결과에 맞춰 갱신한다.

## 0. 작업 기준

| 항목 | 확인 결과 |
| --- | --- |
| PR #91 (휴대폰 사진 HEIC·HEIF 호환) | 2026-11-25 main에 병합됨 → 충돌 없음, main을 기준으로 사용 |
| 새 브랜치 | `feature/ai-visual-critique` ← `origin/main` |
| 미커밋 파일 | `docs/ai-review-v1.2-plan.md`, `docs/release-v1.1.md`, `e2e/prod_reference_flow.py` 그대로 유지 (untracked) |

## 1. 기존 구조 분석

### 1-1. AI 첨삭 정리 결과 (재사용 대상)

- `feedback_summaries`: 피드백 1건(녹음 `recording_id` 또는 글 첨삭 `note_id`)당 현재 첨삭 1개
  (DRAFT → IN_REVIEW → APPROVED). `ai_output`은 불변 AI 원본, `summary`·항목은 사람이 고친 현재 값.
- `feedback_items`: `kind` = STRENGTH(잘한 점) / **WEAKNESS(부족한 점)** / **FIX(수정 방법)** / NEXT_TIP,
  `category` = `WeaknessCategory` (구도·형태·비례·투시·명암·색채·재질·묘사·마무리·기타·시간 관리),
  `evidence_segment_ids`로 원문 근거 구간을 가리킴.
- → **이미지 수정에 쓸 개선사항 = 현재 사진에 연결된 피드백의 현재 첨삭에서 WEAKNESS·FIX 항목**.
  새 분석 시스템은 만들지 않는다. 카테고리 체계도 `WeaknessCategory`를 그대로 쓴다.
  TIME_MANAGEMENT(시간 관리)는 그림으로 반영할 수 없으므로 제외한다.

### 1-2. 사진 ↔ 피드백 연결

- `feedback_image_refs` (v0.9.8): 피드백 1개 ↔ 기준 사진 N장, 행으로 고정 저장.
- 사진 교체: 새 `artwork_photos` 행 + `replaces_photo_id`, 교체 전 사진은 DELETED. 피드백 기준 사진이면
  파일을 남김(`storage_cleanup_pending=false`) → `_replaced_reference`로 계속 조회 가능.
- 프론트 `groupStageFeedback`: `byPhoto`(지금 사진 피드백) / `beforeReplace`(교체 전 사진 피드백, 새 사진에
  안 셈) / `common`(단계 공통). → **개선사항 수집은 `byPhoto`와 같은 기준(서버에서 재계산)**:
  기준 사진이 *지금 그 ACTIVE 사진*인 피드백만. 교체 전·단계 공통·작품 전체·다른 단계 피드백은 제외.

### 1-3. 화면·컴포넌트

- 아카이브 상세 `ArtworkDetailPage` → `StagePhotos`(단계 헤더·`PhotoCarousel`·교체/삭제·피드백 등록·
  '단계 피드백 보기' 버튼). 여기에 'AI 수정본 보기' 버튼만 추가 (이미지는 펼치지 않음).
- 단계별 피드백 `ArtworkFeedbackPage` (`/artworks/:id/feedback?stage=&photo=`) + `FeedbackList`
  (라우터에서 주입). 현재 사진 피드백 목록 아래에 '개선사항 + 피드백 반영 수정하기' 영역 추가.
- `PhotoCarousel`: scroll-snap 가로 슬라이드 + 화살표 + 점 표시, 1장이면 화살표·점 없음.
  **AI 수정본 화면에서 그대로 재사용**하되, 비교 슬라이더가 있는 비교 모드에서는 슬라이드 안 콘텐츠를
  바꿔야 하므로 `renderSlide` 옵션(기본값은 기존 `ArtworkPhoto`)을 추가하는 방식으로 확장한다.
  기존 호출부 동작은 바뀌지 않는다.

### 1-4. AI 처리 인프라 (재사용)

- DB 작업 큐 `ai_processing_jobs` + Worker(`python -m app.worker`, GitHub Actions `stt-worker.yml`,
  `workflow_dispatch`로 즉시 실행). `FOR UPDATE SKIP LOCKED` + lease/heartbeat → 서버 재시작·Worker
  중단 시 lease 만료 후 회수, 시도 소진 시 FAILED(`WORKER_LOST`). 활성 작업 부분 유니크 인덱스로 중복 방지.
- **외부 AI 키는 Worker에만** (API 서버·프론트 금지), Storage는 **service_role 없이 사용자 토큰 + RLS**.
- 외부 AI 전송 동의 `ai_processing_consents` (제공자별·목적별, 연령 구간·보호자 확인).
- 알림 `notifications` (`NotificationService.notify`, 유형 enum 추가로 확장 가능).

## 2. 이미지 수정 모델 검토 (공식 문서, 2026-11-26 확인)

| 모델 (ID) | 수정 입력 | 가격 (Standard) | 비고 |
| --- | --- | --- | --- |
| OpenAI `gpt-image-2.5-flare` | ✅ `/v1/images/edits` | 텍스트 입력 $5, 이미지 입력 $8, 이미지 출력 $30 /1M 토큰 | "빠른 일상 생성". **ZDR 호환 목록 포함**. 학습 미사용 |
| OpenAI `gpt-image-2.5-sunburst` | ✅ | 동일 토큰 단가 (고품질일수록 출력 토큰↑) | "편집 정밀도가 가장 중요한 작업용". ZDR 호환 |
| OpenAI `gpt-image-2.6-flare` | ✅ | 동일 | `complexity`(low로 국소 수정) 지원, **ZDR 목록에 없음**, Batch 불가 |
| Google `gemini-nano-banana-2.1` | ✅ (Interactions API) | 입력 $1.50, 이미지 출력 $30 /1M → 1K 약 **$0.034**/장, 2K $0.050 | 유료 등급만, 유료 데이터 학습 미사용, SynthID 워터마크 |
| Google `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite) | ✅ | 1K 약 $0.034/장 | 저비용 |

- 지원 해상도: OpenAI `size` 1024x1024·1536x1024·1024x1536·auto·사용자 지정(16의 배수, 655,360~8,294,400px).
  Gemini 1K/2K/4K, 다양한 화면비.
- 응답 시간: OpenAI "복잡한 프롬프트는 최대 2분". Gemini는 공식 수치 없음. + Worker 기동(GitHub Actions)
  1~2분 → **실사용 체감 약 1~4분 예상** (실측 필요).
- 사용 제한: OpenAI 기본 IPM 20(Build 등급), Gemini Tier 1은 AI Studio에서만 확인 가능·10분 $10 지출 한도.
- OpenAI는 이미지 입력을 CSAM 분류기로 검사하며, 탐지 시 ZDR이어도 수동 검토용으로 보관.

### ⚠️ 상업 서비스·미성년자 조건 (가장 큰 결정 사항)

- **Gemini API 약관: "18세 이상만 사용", "18세 미만이 이용하거나 이용할 가능성이 높은 앱에 사용 금지"**.
  ART MATE는 입시생(대부분 만 14~18세) 대상이므로 Gemini 이미지 모델은 **서비스 전체 기준으로 부적합**.
  (기존 요약 기본 제공자를 OpenAI로 바꾼 v0.9.6 판단과 같은 이유.)
- OpenAI: Under-18 guidance + 기존 연령별 게이트(`AI_TEENS_ENABLED`, `AI_UNDER14_ENABLED`+ZDR) 그대로 적용.
  `gpt-image-2.5-*`는 ZDR 호환 → 만 14세 미만 확장 시에도 같은 조건으로 운영 가능.

### 권장안

- **기본 모델: OpenAI `gpt-image-2.5-flare`, quality `medium`, size = 원본 비율에 가까운 지원 크기**
  (세로 1024x1536 / 가로 1536x1024 / 정사각 1024x1024). 품질 부족 시 환경변수로 `sunburst`로 전환.
- 환경변수: `IMAGE_EDIT_ENABLED`, `IMAGE_EDIT_PROVIDER`(openai|gemini), `IMAGE_EDIT_MODEL`,
  `IMAGE_EDIT_QUALITY`, `IMAGE_EDIT_TIMEOUT_SECONDS`, 한도 값. 모델 ID는 코드에 하드코딩하지 않고 설정
  기본값 1곳에만 둔다. Gemini 어댑터도 같은 인터페이스로 만들되 배포 환경에서는 약관 확인 플래그 없이는 막는다.

### 예상 비용 (추정 — 실측으로 확정)

| 항목 | gpt-image-2.5-flare medium 추정 |
| --- | --- |
| 입력 이미지 (원본 + 제시물 사진 최대 1장) | 약 2~6천 토큰 × $8/1M ≈ $0.02~0.05 |
| 텍스트 프롬프트 | 약 1~1.5천 토큰 × $5/1M ≈ $0.01 |
| 출력 이미지 1장 | 약 1.4~2천 토큰 × $30/1M ≈ $0.04~0.06 |
| **1회 합계** | **약 $0.07~0.12 (약 100~170원)** |
| 승인 요청 실측 테스트 | 3단계 × 1장 = **3회, 최대 약 $0.40** |
| 운영 예시 | 학생 100명 × 월 20회 한도 전부 사용 = 2,000회 ≈ $140~240/월 (상한) |

토큰 단가는 공식 문서 값이고, 장당 토큰 수는 2.5 계열 공식 계산표가 없어 추정이다. 실제 호출 응답의
`usage`로 기록해 확정한다.

## 3. 데이터 설계 (기존 네이밍 규칙)

### 3-1. `artwork_ai_revisions` (신규, AI 수정본 1개 = 생성 요청 1건)

| 필드 | 설명 |
| --- | --- |
| `id`, `created_at`, `updated_at` | UUIDPrimaryKeyMixin, TimestampMixin |
| `artwork_id`, `owner_id` | `(artwork_id, owner_id)` → `artworks` 복합 FK, CASCADE |
| `stage_id` | `(stage_id, artwork_id)` → `artwork_stages` 복합 FK |
| `photo_id` | `(photo_id, artwork_id)` → `artwork_photos` 복합 FK. **원본 사진 행 id 자체가 버전 식별자** (교체하면 새 행) |
| `source_sha256` | 생성 당시 원본 파일 해시 (파일 동일성 검증·재사용 키) |
| `version` | 같은 `photo_id` 안에서 1, 2, 3… (`UNIQUE(photo_id, version)`) |
| `status` | `AiRevisionStatus`: QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELLED (+ 화면의 '생성 전'은 행 없음) |
| `job_id` | `ai_processing_jobs` FK (SET NULL) — 큐·lease·재시도는 기존 작업 테이블 재사용 |
| `storage_path` | 신규 비공개 버킷 `ai-revisions`의 `{owner}/{artwork}/{revision}.png` (성공 시) |
| `width`, `height`, `content_type`, `size_bytes` | 결과 이미지 메타데이터 |
| `source_feedback_ids` | JSONB `[{"type": "RECORDING"/"NOTE", "id", "summary_id", "summary_version"}]` |
| `improvements` | JSONB **스냅샷** `[{"key", "category", "category_label", "text", "kind", "feedback_id", "item_id"}]` — 생성 당시 보낸 개선사항 전부 (이후 피드백이 바뀌어도 불변) |
| `selected_keys` | 학생이 고른 개선사항 key 목록 (후보 중 선택 정보) |
| `provider`, `model_name`, `prompt_version`, `settings` | 사용 모델·설정(quality, size) |
| `request_hash` | sha256(원본 sha256 + 정렬된 개선사항 텍스트 + 모델 + 설정 + prompt_version) — **결과 재사용·중복 방지 키** |
| `requested_at`, `started_at`, `finished_at`, `duration_ms` | 생성 시각·소요 시간 |
| `api_call_count`, `input_tokens`, `output_tokens`, `estimated_cost_usd` | 사용량·예상 비용 (실패 시도 포함 누적) |
| `error_code`, `error_message` | 안전한 실패 원인만 |
| `deleted_at` | 학생이 수정본 삭제 (soft delete + `storage_cleanup_pending`) |
| `result_staging` | (BYTEA, 임시) Worker가 만든 이미지 — 아래 3-3 참고, 업로드 후 NULL |

인덱스: 부분 유니크 `(request_hash) WHERE status IN ('QUEUED','RUNNING','SUCCEEDED') AND deleted_at IS NULL`
→ 동시 요청이 DB에서 하나로 합쳐지고, 같은 조건의 성공 결과는 새 호출 없이 반환.
`(owner_id, created_at)` (한도 집계), `(artwork_id, stage_id, photo_id)`. RLS 활성화(정책 없음, 기존과 동일).

### 3-2. 기존 테이블 변경 (기존 데이터 유지)

- `AiJobType`에 `IMAGE_REVISE`, `AiConsentPurpose`에 `VISUAL_CRITIQUE`(작품 이미지 외부 전송 별도 동의),
  `NotificationType`에 `AI_REVISION_READY` 추가 (enum 값 추가만).
- `ai_processing_jobs`: `revision_id` FK 컬럼 + 활성 작업 부분 유니크 인덱스 + CHECK 추가.
- Alembic `0017_v1_3_ai_visual_critique` 한 개. 기존 행 변경 없음, downgrade 제공.

### 3-3. Worker 결과 저장 (service_role 없이)

Worker는 사용자 토큰이 없으므로 Storage에 직접 올릴 수 없다. 두 단계로 처리한다.

1. 요청 시 API 서버가 사용자 토큰으로 원본 사진(·제시물 사진) **다운로드용 Signed URL**을 발급해 작업에 저장
   (기존 TRANSCRIBE의 `source_url` 방식, 응답·로그 비노출, 끝나면 삭제).
2. Worker가 이미지 생성 → 결과를 `result_staging`에 저장, 상태 `SUCCEEDED`(파일 업로드 대기 표시).
3. 학생 화면이 상태를 조회할 때(또는 알림 진입 시) API 서버가 **그 학생의 토큰으로** Storage 업로드 →
   `storage_path` 기록, `result_staging = NULL`. 업로드 실패해도 결과는 DB에 남아 다음 조회 때 재시도
   (API 재호출 없음).

### 3-4. 사진 교체·삭제 정책

- 수정본은 `photo_id`(그 시점 원본 행)에 묶인다 → 교체 후 새 사진은 수정본 0개로 시작, 교체 전 수정본은
  새 사진의 '교체 전 사진 수정 이력'으로 따로 보여 준다(기존 `_successors` 재사용). 원본으로 잘못 표시하지 않음.
- 교체·단독 삭제 시 원본 파일: 수정본이 참조 중이면 피드백 기준 사진과 같은 방식으로 **파일을 남김**
  (`is_feedback_reference` 판정에 수정본 참조를 추가) → 비교 화면이 깨지지 않음.
- 수정본 삭제 → 수정본 행·파일만 정리, 원본 사진 영향 없음. 마지막 참조가 사라진 교체 전 원본 파일은 정리.
- 작품 삭제 → 수정본 전부 DELETED + 파일 정리 대기, 진행 중 작업 CANCELLED (기존 delete 흐름에 추가).
- 외부 AI 동의 철회 → 대기·진행 중 생성 작업 취소, 결과 저장 안 함 (기존 요약과 동일).

## 4. API (학생 본인만, 다른 사람 작품 → 404)

| 메서드·경로 | 설명 |
| --- | --- |
| `GET /artworks/{id}/ai-revisions/summary` | 단계별 수정본 개수 (아카이브 상세 버튼) — 이미지 API 미호출 |
| `GET /artworks/{id}/stages/{stage_id}/ai-revisions` | 단계의 사진별 수정본 목록(최신 먼저) + 교체 전 이력, Signed URL |
| `GET /artworks/{id}/photos/{photo_id}/ai-revision-candidates` | 개선사항 후보 (현재 사진 피드백의 WEAKNESS·FIX, 중복 통합) + 정리 안 된 피드백 수·한도 남은 횟수 |
| `POST /artworks/{id}/photos/{photo_id}/ai-revisions` | 생성 요청 `{selected_keys, idempotency_key}` → 202 (재사용이면 200 + 기존 수정본) |
| `GET /ai-revisions/{id}` | 상태 조회 (폴링, 업로드 대기분 마무리) |
| `POST /ai-revisions/{id}/retry` | 실패한 생성 재시도 (새 버전, 한도 차감) |
| `DELETE /ai-revisions/{id}` | 수정본 삭제 |

### 개선사항 수집 규칙 (서버)

1. 현재 ACTIVE 사진을 기준 사진으로 가진 피드백만 (`feedback_image_refs`, 교체 전·공통·전체 제외).
2. 각 피드백의 **현재 첨삭**(DRAFT·IN_REVIEW·APPROVED)에서 WEAKNESS·FIX 항목. 첨삭이 없는 피드백 수는
   `unsummarized_count`로 알려 '먼저 AI 첨삭 정리' 안내.
3. 같은 카테고리의 WEAKNESS + FIX를 한 개선사항으로 묶고, 정규화한 문장이 같은 항목은 합친다
   (LLM 추가 호출 없이 규칙 기반 — 비용 0, 없는 내용 생성 불가).
4. TIME_MANAGEMENT 제외, 빈 결과면 생성 불가(422).
5. 요청 시 서버가 같은 규칙으로 다시 계산해 학생이 보낸 key와 대조 → 프론트가 임의 문장을 보낼 수 없음.

## 5. 비용·중복 방지

- 학생이 버튼을 눌렀을 때만 생성 (업로드·피드백 등록 때 자동 생성 없음, 조회·비교는 이미지 API 미호출).
- 프론트: 요청 중 버튼 잠금 + 요청별 `idempotency_key`. 백엔드: `request_hash` 부분 유니크 인덱스 +
  행 잠금 → 동시에 여러 번 눌러도 1건. 같은 원본·같은 개선사항·같은 설정의 성공 결과는 재사용.
- 한도(서버 검증): `IMAGE_EDIT_DAILY_LIMIT`(기본 3), `IMAGE_EDIT_MONTHLY_LIMIT`(기본 20), 재사용은 미차감.
  향후 회원 등급별 한도를 위해 `image_edit_limits(plan)` 조회 함수 1곳으로 분리 (결제·구독은 구현 안 함).
- 자동 재시도: 네트워크·5xx·429만, **최대 2회 시도**(`IMAGE_EDIT_MAX_ATTEMPTS`). 콘텐츠 거부·잘못된 입력은
  재시도 없음. 시도마다 호출 수·토큰·예상 비용 누적, 성공/실패 구분 기록.
- 멈춘 작업: 기존 lease 만료 회수 + `WORKER_LOST`. 업로드 대기 결과는 조회 때 마무리.

## 6. 프롬프트

요청서 8-3의 기본 프롬프트 + 8-4 단계별 조건을 `app/services/ai_revision_prompt.py`에 버전(`prompt_version`)과
함께 둔다. 단계 판정은 `legacy_stage`(SKETCH/PROGRESS/FINAL)로 한다 (사용자 정의 단계명 대응).
전달: 원본 이미지, 단계, 작품 주제(`topic`), 실기 유형, 제시물 사진(있으면 첫 장), 선택한 개선사항 문장.
보내지 않음: 음성·전사 원문, 이름·학원·작품 제목·자유 메모, 강사 정보. 개선사항 문장은 기존
`ai_redaction`으로 개인정보 패턴을 가린 뒤 보낸다. OpenAI에는 사용자 id 해시를 `safety_identifier`로 보낸다.

## 7. 화면

1. **아카이브 상세**: 각 단계 '단계 피드백 보기' 아래 `✨ AI 수정본 보기 (N개) →` (같은 너비, 주황 계열
   보조 버튼). 0개여도 표시. 수정본 이미지는 펼치지 않음.
2. **단계별 피드백**: 현재 사진 피드백 목록 아래 'AI 수정에 반영할 개선사항'(체크박스, 기본 전체 선택,
   카테고리 칩) + `✨ 피드백 반영 수정하기`. 미정리 피드백 안내, 없으면 비활성, 기존 수정본 보기 버튼,
   생성 중·실패·완료 상태, 외부 AI 전송 안내·동의. 사진을 넘기면 함께 바뀜.
3. **AI 수정본 화면** `/artworks/:id/stages/:stageId/ai-revisions?photo=&revision=`:
   제목 '스케치 AI 수정본' 등, `사진 n / N`, `PhotoCarousel` 재사용(수정본 없는 사진도 포함),
   `원본 | 비교 | AI 수정작` 탭(수정본 있으면 비교, 없으면 원본), 반영 요청한 개선사항(스냅샷,
   '수정에 요청한 개선사항'), 생성 시각·모델, `수정 이력 보기 (N개)`(썸네일·버전·시각·개선사항·모델·비교·삭제),
   하단 학습용 참고 이미지 안내 문구.

### 비교 슬라이더 구현

- 두 이미지를 같은 상자에 `object-fit: contain`으로 겹치고, 상자 비율 = 원본 비율. AI 수정본 비율이 다르면
  늘리지 않고 contain 여백으로 맞춤(왜곡 없음). 수정본을 `clip-path: inset(0 0 0 X%)`로 잘라 보여 줌.
- 핸들은 Pointer Events + `setPointerCapture`, 핸들·슬라이더 영역 `touch-action: pan-y`(세로 스크롤은 유지,
  가로 제스처만 슬라이더가 가져감) + `stopPropagation` → 상위 `PhotoCarousel` 스크롤이 움직이지 않음.
  조작 중에는 Carousel에 `locked` 상태를 줘 `overflow-x: hidden`. 키보드 ←/→, `role="slider"`·aria 값.
- 사진 이동은 화살표·점 표시·이미지 영역 밖 스와이프로. 실제 iOS Safari·Android Chrome 수동 검수 항목.

## 8. AI 수정본과 실제 작품 데이터 분리

수정본은 별도 테이블·별도 버킷이고 `artwork_photos`에 넣지 않는다 → 단계 사진 슬라이드·사진 개수·대표 사진·
아카이브 썸네일·성장 리포트·작품 분석·참고작/ArtClip·커뮤니티 공유·데이터셋 쿼리에 구조적으로 들어갈 수
없다. 이를 확인하는 회귀 테스트를 추가한다. 학생이 실제로 고쳐 그린 뒤 올린 사진만 새 작품 사진.

## 9. 보안·개인정보

- 기존 인증·소유권(`ArtworkService.owned`) 적용, 강사·다른 학생 접근 불가(이번 범위는 학생 본인만).
- 새 버킷 `ai-revisions`: 비공개, 정책 함수로 소유자만 읽기·쓰기 (`storage-setup.sql`에 추가), 짧은 Signed URL.
- 키·Signed URL·이미지·개선사항 문장은 로그에 남기지 않음 (작업 ID·코드·소요 시간만).
- **새 동의 목적 `VISUAL_CRITIQUE`**: 작품 사진을 외부 AI로 보내는 것은 기존 '전사문 요약' 동의 범위 밖이므로
  별도 동의(연령 구간·보호자 확인 규칙 동일). 동의 화면 문구·개인정보 처리방침 업데이트 필요.
- 학습 사용 금지: 수정본은 `dataset` 수집 대상에서 제외, 제공자 정책(유료/기본 API 학습 미사용) 확인.

## 10. 테스트 계획

- Fake 이미지 편집 클라이언트(`tests/fake_ai.py` 방식)로 Worker·API 전부 테스트, 실제 호출 없음.
- 단위: 개선사항 수집(사진별 분리·교체 전 제외·중복 통합·TIME_MANAGEMENT 제외), 프롬프트(단계별 조건,
  개인정보 미포함), request_hash, 한도.
- DB 통합(`tests/db`): 마이그레이션, 동시 요청 1건, 재사용, 교체 후 이력 보존·원본 파일 보존, 작품 삭제 정리,
  다른 사용자 404, 대표 사진·성장 분석 제외, Worker lease 회수·재시도 상한·실패 기록.
- 프론트: 개선사항 선택·상태 전환 단위 테스트, 비교 슬라이더 위치 계산, lint, build. 기존 테스트 전체 회귀.
- 실제 생성: 승인 후 스케치·중간·완성 각 1장(3회).

## 11. 위험 요소

| 위험 | 대응 |
| --- | --- |
| Gemini 약관 18세 미만 금지 | 기본 OpenAI. Gemini는 운영자 확인 없으면 배포 환경에서 차단 |
| 모델이 그림을 재창작·구도 변경 | 보존 조건 프롬프트, 원본 비율 크기, quality 설정. 비교 화면에서 왜곡 없이 표시. 실측 후 sunburst 검토 |
| Worker 기동 지연 (GitHub Actions) | 즉시 dispatch, 비동기 UX·알림, 상태 실제값만 표시 |
| 결과 업로드에 사용자 토큰 필요 | DB 임시 저장 후 조회 시 업로드 (3-3) |
| 비용 폭증 | 서버 한도·재사용·재시도 상한·기본 꺼짐(`IMAGE_EDIT_ENABLED=false`) |
| 미성년자 작품 이미지 외부 전송 | 별도 동의 + 기존 연령 게이트 + 처리방침 갱신 (운영자·법률 검토 필요) |
| Supabase 버킷·정책 추가 | 개발 DB에 SQL 적용 필요 (운영 적용은 병합 시) |

## 12. 예상 개발 범위

백엔드: 모델·마이그레이션·enum, 개선사항 수집 서비스, 프롬프트, 이미지 편집 클라이언트(OpenAI·Gemini·Fake),
Worker 작업, API·스키마, 한도·재사용, 교체·삭제 연동, Storage SQL, 테스트.
프론트: API 모듈, 아카이브 버튼, 피드백 화면 개선사항 패널, AI 수정본 페이지·비교 슬라이더·이력 시트,
Carousel `renderSlide` 확장, 동의 연결, 테스트. 문서: 이 문서 갱신, 프론트 연동 가이드, 처리방침 항목.

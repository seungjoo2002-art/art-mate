# AI 시각적 첨삭 (AI 수정본) v1.3 — 구현·운영·개인정보 검토

> 계획: [ai-visual-critique-v1.3-plan.md](ai-visual-critique-v1.3-plan.md). 이 문서는 실제 구현 기준이다.
> 기능은 **기본 꺼짐**이다. 운영자 검토(§6) 전에는 실제 사용자에게 보이지 않는다.

## 1. 흐름

1. 단계별 피드백 화면(`/artworks/:id/feedback?stage=&photo=`)의 '이 사진 피드백' 아래
   **AI 수정에 반영할 개선사항** 패널이 지금 사진의 개선사항 후보를 보여 준다 (기본 전체 선택).
2. 학생이 고른 개선사항으로 **✨ 피드백 반영 수정하기** → `POST /artworks/{id}/photos/{photo}/ai-revisions`.
   서버가 후보를 다시 계산해 대조하고, 동의·한도를 확인한 뒤 수정본(QUEUED)과 `IMAGE_REVISE` 작업을 만든다.
3. Worker(GitHub Actions `stt-worker`)가 원본을 받아 정리(방향 적용·EXIF/GPS 제거·긴 변 1536px)하고
   OpenAI 이미지 수정 API를 호출한다. 결과는 DB에 임시 저장(STORING), 앱 알림 `AI_REVISION_READY`.
4. 학생이 다음에 AI 수정본 관련 화면을 열면 API 서버가 **학생 토큰으로** Storage(`ai-revisions`)에 올리고
   임시 이미지를 지운다(SUCCEEDED).
5. 아카이브 상세 단계마다 '단계 피드백 보기' 바로 아래 **✨ AI 수정본 보기 (N개)** →
   `/artworks/:id/stages/:stageId/ai-revisions` (원본 사진별 가로 슬라이드, 원본 | 비교 | AI 수정작, 수정 이력).

## 2. 개선사항 (기존 AI 첨삭 정리 재사용, 새 LLM 호출 없음)

- 대상 피드백: 같은 단계의 녹음(ACTIVE)·글 첨삭 중 **기준 사진(`feedback_image_refs`)이 지금 이 사진 행**인 것만.
  교체 전 사진·다른 사진·단계 공통·작품 전체·다른 단계 피드백은 넣지 않는다.
- 항목: 현재 첨삭(DRAFT·IN_REVIEW·APPROVED)의 부족한 점(WEAKNESS)·수정 방법(FIX). 시간 관리 카테고리는 제외.
- 같은 카테고리·종류에서 정규화 문장 유사도 ≥ 0.85면 하나로 합친다 (규칙 기반).
- AI 정리가 없는 피드백 수를 함께 알려 '먼저 정리' 안내.

## 3. 데이터

| 표 | 내용 |
| --- | --- |
| `artwork_ai_revisions` (신규, RLS) | 수정본 1개 = 요청 1건. 원본 `photo_id`+`source_sha256`, `version`, 상태, 개선사항 스냅샷(`improvements`)·선택 정보(`selection`)·참조 피드백(`source_feedback`), 모델·설정·프롬프트 버전, `request_hash`, 저장 경로·크기, 임시 결과(`result_staging`), 시각(요청·Worker 시작·API 시작/끝·임시 저장·Storage 저장·화면 표시), 호출 수·토큰·예상 비용, 오류 코드, 삭제 |
| `ai_processing_jobs` | `IMAGE_REVISE`, `revision_id` (+ 진행 중 작업 유니크) |
| `ai_processing_consents` | purpose `VISUAL_CRITIQUE` (제공자 항상 OPENAI) |
| `notifications` | `AI_REVISION_READY`, `ai_revision_id` |
| Storage | 새 비공개 버킷 `ai-revisions` + `can_access_ai_revision_object()` (소유 학생만) |

마이그레이션 `0017` (값·열 추가만, 기존 행 변경 없음, downgrade 있음).
`backend/supabase/storage-setup.sql`의 v1.3 블록을 Supabase에 적용해야 한다.

`0017`은 `can_access_artwork_object()`도 바꾼다: 소유 학생은 **교체됐지만 파일을 남겨 둔 사진**(피드백 기준 사진·
수정본 원본, `status=DELETED AND storage_cleanup_pending=false` + 교체한 사진이 있음)을 읽을 수 있다. 그냥 삭제한 사진은 지금처럼 읽을 수 없다. 이전에는 Storage RLS가 막아
교체 전 사진의 Signed URL이 운영에서 발급되지 않았을 수 있다 (테스트는 메모리 Storage라 드러나지 않았던 기존 문제).

### 실제 작품 데이터와 분리
수정본은 `artwork_photos`에 넣지 않는다 → 단계 사진 슬라이드·사진 수·대표 사진·아카이브 썸네일·성장 분석·
참고작·커뮤니티 공유·데이터셋(모두 `artwork_photos`·피드백만 읽음)에 구조적으로 들어가지 않는다 (테스트로 확인).

### 사진 교체·삭제
- 교체: 새 사진은 새 원본(수정본 0개). 교체 전 수정본은 그때의 원본 행에 남아 '교체 전 사진의 수정본'으로
  이력에 보이고, 비교도 그때의 원본과 한다. 원본 파일은 수정본이 있는 동안 남긴다.
- 수정본 삭제: 수정본만 지운다. 교체 전 원본을 수정본 때문에만 남겨 뒀다면 그 파일도 정리.
- 원본 사진 삭제: 그 자리(교체 전 사진 포함)의 수정본도 삭제·진행 중 작업 취소 (원본 없는 비교 방지).
- 작품 삭제: 수정본 전부 삭제·파일 정리·작업 취소.

## 4. 비동기·저장 (Worker는 Storage에 쓸 수 없음)

- Worker 결과 → `result_staging`(DB) → 학생 조회 때 학생 토큰으로 업로드. 행 잠금 `FOR UPDATE SKIP LOCKED`로
  동시 조회에도 1번만 올린다. 업로드 실패 시 임시 이미지를 유지하고 다음 조회에서 **저장만** 재시도
  (생성 API 재호출 없음). 같은 경로에 이미 있으면(이전 시도 성공 후 DB 실패) 업로드 완료로 본다.
- 저장 확인 후에만 임시 이미지를 지운다.
- 보관: 학생이 `IMAGE_EDIT_STAGING_RETENTION_DAYS`(기본 14일) 안에 열지 않으면 Worker 정기 작업이 임시
  이미지를 지우고 `FAILED(RESULT_EXPIRED)` (생성 API를 다시 부르지 않음, 학생은 다시 만들 수 있음).
  운영 확인: `GET /admin/ai-revisions/usage`의 `staged_results`·`staged_bytes`.
- **한계**: 최종 저장은 학생이 아카이브 상세·피드백 화면·AI 수정본 화면 중 하나를 열어야 끝난다. 그 전까지
  결과는 DB에만 있다 (최대 결과 8MB × 대기 수). 알림을 누르면 바로 저장된다. 학생이 오래 열지 않으면 만료된다.
- 서버 재시작·Worker 중단: 기존 lease 회수. 요청을 보낸 뒤 멈춘 시도는 **자동으로 다시 보내지 않고**
  `IMAGE_RESULT_UNKNOWN`으로 끝낸다 (중복 과금 방지).

## 5. 비용·중복

- 학생이 버튼을 눌렀을 때만 생성. 업로드·피드백 등록·조회·비교·저장 재시도는 생성 API를 부르지 않는다.
- `request_hash`(원본 해시 + 개선사항 + 모델·품질·크기·형식 + 제시물 해시 + 프롬프트 버전) 부분 유니크 +
  생성 요청 직렬화(advisory lock) → 동시 요청 1건, 같은 요청은 기존 결과 200.
- 한도(서버 검증, Asia/Seoul): 학생별 일 3·월 20(설정), 서비스 하루 30건·월 예상 비용 $10(설정).
  한도는 '진행 중·결과 있음·실제 API 호출'만 센다 (호출 전에 취소·실패한 요청은 세지 않음. 지워도 돌아오지 않음).
  회원 등급별 한도는 `AiRevisionService.quota()` 한 곳에서 확장 (결제·구독 미구현).
- 자동 재시도(최대 `IMAGE_EDIT_MAX_ATTEMPTS`=2): 전송 전 연결 실패, 429 rate limit, 500·502·503만.
  응답 대기 시간 초과·504·응답 중 끊김·인증·한도(insufficient_quota)·정책 거부·잘못된 요청은 재시도 안 함.
- 호출 수·토큰(텍스트/이미지 입력, 출력)·예상 비용을 수정본과 작업에 누적 (실패 호출 포함).

## 6. 운영자·법률 검토 (기능을 켜기 전)

**현재 상태: 미검토 → `IMAGE_EDIT_OPERATOR_CONFIRMED=false`.**

| 항목 | 확인할 것 |
| --- | --- |
| OpenAI 미성년자 이용 | OpenAI Under-18 API guidance: 18세 미만 대상 서비스는 연령에 맞는 안내·필터·모니터링, "13세 미만 또는 해당 지역 디지털 동의 연령 미만"은 ZDR 적용 전 처리 금지. 국내 기준 만 14세 미만은 기존과 같이 `AI_UNDER14_ENABLED`+`AI_ZDR_APPROVED`+ZDR 호환 모델일 때만 |
| ZDR | `gpt-image-2.5-*`는 OpenAI 문서상 이미지 엔드포인트 ZDR **호환** 모델이다. **이 조직에 ZDR이 승인·적용됐는지는 별개**이며 현재 승인되지 않았다(`AI_ZDR_APPROVED=false`). 동의서에도 "아직 적용되어 있지 않아요"로 고지. 승인되면 동의서 문구·버전 갱신 |
| 데이터 보관 | OpenAI: API 입력 학습 미사용(기본), 남용 감시 로그 최대 30일, 이미지 입력은 CSAM 검사 후 의심 시 ZDR이어도 수동 검토용 보관 |
| 국외 이전 | 개인정보 보호법 제28조의8: 이전 국가·업체·항목·목적·보관 기간 고지 및 동의 (동의서 '제공받는 곳·보내는 내용·보관' 항목) |
| 법정대리인 | 제22조의2: 만 14세 미만 법정대리인 동의·확인 (기존 보호자 링크 절차 재사용) |
| 동의 범위 | 작품 **이미지** 전송은 기존 '전사문 요약' 동의 밖 → 별도 동의 `VISUAL_CRITIQUE` (버전 `2026-12-visual-v1`) |
| 처리방침 갱신 | 처리 항목(작품 사진, 개선사항 문장), 목적(학습용 수정 예시), 수탁·국외 이전(OpenAI, 미국 등), 보관(수정본: 학생 삭제·작품 삭제까지 / 임시 결과 14일 / OpenAI 로그 최대 30일), 학습 미사용, 거부 권리 |
| 학습 데이터 | 수정본은 데이터셋·모델 학습에 쓰지 않음 (구조적으로 제외) |
| 사진 속 개인정보 | 작품 사진에 이름·학교가 적혀 있으면 함께 전달될 수 있음 (동의서 고지). 필요하면 업로드 안내 추가 |

켜는 순서: 법률 검토·처리방침 반영 → Supabase에 storage-setup v1.3 적용 → Render·GitHub Actions에
`IMAGE_EDIT_ENABLED=true`, `IMAGE_EDIT_OPERATOR_CONFIRMED=true`(+ 기존 `AI_PROVIDER_TERMS_CONFIRMED=true`,
Secret `OPENAI_API_KEY`) → 운영 테스트 계정으로 확인.

## 7. 키·로그

- OpenAI 키는 Worker(GitHub Actions Secret)에만. API 서버·프론트·저장소·로그에 넣지 않는다.
- 로그: 작업·수정본 ID, 오류 코드, HTTP 상태, 소요 시간만. 이미지·프롬프트·개선사항·Signed URL·키는 남기지 않는다.
- `safety_identifier`: 사용자 ID의 SHA-256 (원문·이메일 아님).

## 8. API

| 메서드·경로 | 설명 |
| --- | --- |
| `GET /artworks/{id}/ai-revisions/summary` | 단계별 완성·진행 중 수 |
| `GET /artworks/{id}/stages/{stage}/ai-revisions` | 단계 수정본 (최신 먼저) + 교체 전 원본 목록 |
| `GET /artworks/{id}/photos/{photo}/ai-revision-candidates` | 개선사항 후보·한도·동의·최근 수정본 |
| `POST /artworks/{id}/photos/{photo}/ai-revisions` | 생성 (202 새 요청 / 200 재사용) |
| `GET /ai-revisions/{id}` | 상태·결과 (저장 대기면 저장) |
| `POST /ai-revisions/{id}/retry` | 실패한 수정본 다시 (새 버전, 한도 차감) |
| `DELETE /ai-revisions/{id}` | 삭제 (원본 사진 영향 없음) |
| `GET /admin/ai-revisions/usage?days=30` | 사용량·예상 비용 (ADMIN) |
| `GET /meta/ai-features` | `ai_revision_status` (ENABLED/DISABLED/UNCONFIRMED), 한도 |

## 9. 화면

- 아카이브 상세: 단계 '피드백 보기' 바로 아래 같은 폭의 연주황 버튼. 기능이 꺼져 있고 수정본도 없으면 숨김
  (운영 화면은 켜기 전까지 그대로). 수정본 이미지는 펼치지 않는다.
- 피드백 화면 패널: 체크박스(기본 전체), 미정리 안내, 동의 이동, 한도, 외부 AI 전달 안내, 실제 상태
  (대기·생성 중·저장 중·실패·완료), 다시 만들기, 기존 수정본 보기 (N개). 4초마다 상태 확인 (화면이 보일 때만).
- AI 수정본 화면: 사진 n / N + 이전·다음(터치 화면에서도 보임), 원본 | 비교 | AI 수정작 (기본 비교, 수정본
  없으면 원본), 사진별 가로 슬라이드(수정본 없는 사진 포함 → 빈 상태 + 피드백 화면 이동), 크게 보기,
  '수정에 요청한 개선사항'(생성 당시 스냅샷), 수정 이력(썸네일·시각·버전·개선사항·모델·비교·삭제), 하단 안내.
- 비교 슬라이더: 상자 비율 = 원본 비율, 두 이미지 `object-fit: contain`(왜곡 없음), AI 수정작 층을
  `clip-path`로 자름. 상자 `touch-action: pan-y` → 가로 손가락 움직임은 손잡이가, 세로는 화면 스크롤이
  가져간다. pointer 이벤트를 위로 보내지 않고 조작 중 슬라이드 잠금. 키보드 ←/→·Home/End.
- 공통 `PhotoCarousel`: 선택 prop만 추가(`renderSlide`·`canOpen`·`locked`·`className`). 그리고 코드로
  이동하는 동안 지나가는 칸을 선택으로 알리지 않게 고쳤다 (`?photo=`로 두 번째 이후 사진을 열면 첫 사진으로
  되돌아가던 문제 — 데스크톱 E2E에서 발견).

## 10. 테스트

- 백엔드 단위 `tests/test_ai_revision_units.py`, DB 통합 `tests/db/test_v13_ai_revisions.py` (가짜 이미지 편집기).
  개발자 셸에 `OPENAI_API_KEY`가 있어도 테스트가 실제 API를 부르지 않게 conftest에서 지운다.
- 프론트 `revisionView.test.js`, `consentCopy.test.js`.
- 브라우저 `e2e/local_ai_revision_flow.py` (로컬 API + 로컬 DB + Chromium, 모바일 390px·데스크톱 1280px,
  가짜 이미지 편집기). 터치는 CDP 터치 이벤트로 실제 브라우저 스크롤·scroll-snap을 일으킨다.
- 실제 OpenAI 점검 `e2e/real_image_edit_check.py` (`--yes` 없으면 호출 안 함).

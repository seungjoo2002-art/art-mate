# VER.2 — P2 설계안 (승인 전, 구현 안 함) · 기존 시스템 확인 결과

> 작성 2026-11-11. P2는 **설계만** 한다. 승인 후 별도 PR·마이그레이션(`0012~`)으로 구현.

## A. P2 설계안

### A1. 사용자별 실기 유형 추가·이름 변경·삭제

현재 `practical_type`은 고정 enum(BASIC_DESIGN 등 6개, varchar+CHECK)이고 프로필·작품·게시물·추천·참고작 점수에 쓰인다.
고정 값을 사용자 데이터로 바꾸면 통계·참고작 매칭이 깨지므로 **고정 유형은 유지하고 사용자 정의 유형을 덧붙이는** 방식을 제안한다.

| 항목 | 설계 |
| --- | --- |
| 테이블 | `user_practical_types` (id, user_id CASCADE, name 1~30자, base_type 고정 enum NULL 허용, position, archived_at) · 유니크 (user_id, lower(name)) WHERE archived_at IS NULL · 사용자당 20개 |
| 작품 | `artworks.custom_practical_type_id` (SET NULL) 추가. 기존 `practical_type`은 그대로 → 통계·참고작은 `base_type`(또는 기존 값) 기준 |
| API | `GET/POST /users/me/practical-types`, `PATCH /{id}`(이름·base_type·순서), `DELETE /{id}` → **보관(archived)** 처리 (기존 작품 표시명 유지) |
| 이름 변경 | 작품에는 id만 저장 → 이름 바꾸면 모든 작품에 반영 |
| 삭제 | 작품이 있으면 보관만, 없으면 실제 삭제 |
| 결정 필요 | 사용자 유형을 커뮤니티 필터·성장 분석 분류에 노출할지 (권장: base_type으로만 집계) |

### A2. 학업 성적·모의고사 기록

민감도가 높은 개인정보(성적)라 **본인 전용**, 강사·커뮤니티 비공개, AI 외부 전송 제외를 기본으로 한다.

| 항목 | 설계 |
| --- | --- |
| 테이블 | `academic_records` (id, user_id CASCADE, kind SCHOOL_EXAM/MOCK_EXAM/CSAT, exam_date, title, subjects JSONB `[{subject, raw_score, grade, percentile}]`, memo) · 과목별 정규화가 필요하면 `academic_record_subjects` 분리 |
| 검증 | 등급 1~9, 백분위 0~100, 원점수 0~200, 날짜 미래 불가 |
| API | `GET/POST /users/me/academic-records`, `GET/PATCH/DELETE /{id}`, `GET /summary`(과목별 추이) |
| 개인정보 | 동의 항목 추가 필요 (선택 수집), 보관 기간·삭제 정책, 강사 공유는 별도 동의 후 (이번 설계 범위 밖) |
| 결정 필요 | 과목 목록 고정 여부, 지망 대학별 반영 비율 계산(합격 예측은 계속 제외) |

### A3. 홈 AI 브리핑 자동 생성

| 항목 | 설계 |
| --- | --- |
| 입력 | 최근 7일 규칙 기반 통계(성장 분석·학습 시간·미완료 과제·다가오는 일정) — 숫자는 서버가 만들고 AI는 문장만 |
| 생성 | GitHub Actions Worker의 정기 작업에 `HOME_BRIEFING` 작업 추가, 학생당 하루 1회, 데이터 지문이 같으면 재사용 |
| 저장 | `home_briefings` (user_id, date, metrics JSONB, narrative JSONB, status, model, tokens) · 유니크 (user_id, date) |
| 동의·비용 | `GROWTH_COACHING` 동의가 있는 학생만, 실패 시 규칙 기반 문장으로 대체, 하루 호출 상한 설정값 |
| API | `GET /growth/me/briefing` (없으면 규칙 기반 즉시 응답 + `ai_status`) |
| 결정 필요 | Gemini 무료 등급 데이터 이용 약관 문제(학생 데이터) — STT 문서와 같은 결정이 먼저 필요 |

### A4. 커뮤니티 게시물 여러 장 사진

| 항목 | 설계 |
| --- | --- |
| 테이블 | `community_post_images` (post_id CASCADE, image_id → shared_artwork_images, position 0~9) · 유니크 (post_id, position), (post_id, image_id) |
| 호환 | `community_posts.image_id`는 대표(첫 장)로 유지 → 기존 응답 그대로, `images[]` 필드 추가 |
| 사진 | 지금의 POST 이미지 방식 재사용 (원본 사진당 파생 이미지 1개, 게시물이 ACTIVE일 때만 공개). RLS 함수의 `p.image_id = i.id` 조건을 `community_post_images` 조회로 확장 |
| 제한 | 최대 10장, 같은 작품의 사진만 (다른 작품 섞기 불가) |
| 삭제 | 사진 삭제 시 그 장만 빠짐, 게시물 삭제·철회 시 전부 정리 (현재 규칙 확장) |

## B. 기존 시스템 확인 결과 (코드·설정에서 확인 가능한 범위)

### B1. STT_ENABLED · AI_SUMMARY_ENABLED · GROWTH_AI_ENABLED · GEMINI_API_KEY

| 위치 | 확인 결과 |
| --- | --- |
| 코드 기본값 (`backend/app/core/config.py`, `.env.example`) | 모두 `false` / 키 없음 |
| 로컬 `backend/.env` | 네 값 모두 **설정 없음**, `SUPABASE_ANON_KEY`는 빈 값 |
| GitHub Actions | Secret: `WORKER_DATABASE_URL`만 있음. `GEMINI_API_KEY` 없음, 변수(`AI_SUMMARY_ENABLED` 등) 없음 → Worker는 STT만 처리 가능, 요약은 큐에 남음 |
| `stt-worker` 실행 이력 | **없음** (예약·수동 실행 기록 0건) |
| Render (API) | **직접 확인 불가** → 대시보드에서 `STT_ENABLED`, `AI_SUMMARY_ENABLED`, `STT_SOURCE_URL_SECONDS`, `SUPABASE_ANON_KEY` 확인 필요 |

### B2. Render와 GitHub Actions Worker 역할

| | Render (API) | GitHub Actions (`stt-worker.yml`) |
| --- | --- | --- |
| 하는 일 | 요청 처리, 전사·요약 **작업 등록**, 상태 조회, 브라우저 전사 저장 | 큐 처리: faster-whisper 전사, Gemini 요약·성장 AI, 정기 작업(보관 기간·알림) |
| 모델 로드 | 하지 않음 | 전사 작업이 있을 때만 |
| 필요한 비밀값 | DB, Supabase URL·anon key | DB(Session pooler), Gemini 키(요약을 켤 때) |
| 브라우저 전사(v0.9.2) | 학생 기기에서 처리 → API로 저장, 대기 중 서버 작업 취소 | 실패·미지원일 때만 대신 처리 |

### B3. Supabase Auth 비밀번호 최소 길이

- 저장소에서 확인할 수 있는 값: 프론트 회원가입 화면이 **8자 이상**을 검사 (`frontend/src/features/auth/pages/SignupPage.jsx`).
- 서버 쪽 설정(Supabase Auth의 Minimum password length, 기본 6자)은 **코드로 확인 불가** → Dashboard → Authentication → Providers → Email → *Minimum password length* (또는 Auth → Policies의 Password requirements)에서 확인. 프론트와 같게 **8**로 맞추길 권장 (프론트 검사만으로는 API 직접 호출을 막지 못함).

### B4. PR #32 브라우저 STT와 프론트 담당자 수정 충돌

- PR #32는 main에 병합 완료 (2026-11-11 05:18). 충돌은 그때 해결함 (router.jsx, RecordingAiStatus.jsx).
- 이번 VER.2 백엔드 작업(PR #47, P1)은 **프론트 파일을 수정하지 않음** → 프론트 담당자 작업과 파일 충돌 없음. 단 API 변경에 따라 프론트가 고칠 곳은 [frontend-integration-ver2.md](frontend-integration-ver2.md) §5.

### B5. `DELETE /artworks/{id}/sharing/COMMUNITY` 실제 삭제 범위 (VER.2 기준)

| 대상 | 처리 |
| --- | --- |
| 커뮤니티 동의 | `revoked_at` 기록 (이력 보존, 행 삭제 아님) |
| 그 작품의 게시물 | `DELETED` 상태로 변경 (soft delete). 댓글·좋아요·저장·신고 행은 남지만 보이지 않음 |
| 게시물용(POST) 공유 이미지 | 삭제 처리 + Storage 파일 삭제 (학생 토큰으로, 실패 시 다음 요청에 재시도) |
| 대표(PRIMARY) 공유 이미지 | **참고작 동의가 남아 있으면 유지**, 남은 동의가 없으면 삭제 + 파일 삭제 |
| 참고작 추천·저장 | 영향 없음 (참고작 동의는 별개) |
| 원본 작품 사진 (artworks 버킷) | **삭제하지 않음** |
| 채택된 커뮤니티 피드백(PEER 첨삭) | 사본이라 남음 |

### B6. REFERENCE 동의와 이미지 보존

- 원본 사진은 공유 동의와 무관하게 **절대 지우지 않는다** (작품·사진을 본인이 삭제할 때만).
- 공유용 대표 이미지는 COMMUNITY·REFERENCE 중 하나라도 유효하면 유지, 둘 다 철회되면 삭제.
- REFERENCE 철회 시: 그 작품을 가리키는 **모든 학생의 참고작 추천·저장 행 삭제**, 강사 우수 사례 확인 기록은 남음(다시 동의하면 후보로 복귀).
- 게시물용 이미지는 참고작에 쓰이지 않으며 참고작 동의로 공개되지 않는다 (VER.2).

### B7. `GET /users/me/learning-context`

| 항목 | 내용 |
| --- | --- |
| 목적 | 성장·과제 화면에서 학습 맥락을 한 번에 보여 주기 (v0.9 F-1) |
| 응답 | `practical_type`, `grade`, `learning_goal`, `learning_goal_updated_at`, `target_universities[]`(1지망부터) |
| 권한 | 학생 본인만 (강사·다른 학생 비공개), AI 외부 전송에 쓰지 않음 |
| 현재 프론트 사용 | **사용 안 함** (지망 대학 개별 API만 사용) |
| 권장 연결 화면 | 홈 상단 "나의 목표" 카드, 성장 리포트 상단(목표·1지망), 맞춤 과제 화면의 목표 문구 — `/users/me` + 지망 대학 목록 두 번 호출 대신 한 번 |

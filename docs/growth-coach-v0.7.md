# v0.7 AI 개인 맞춤형 성장 코치 — 설계와 운영

> 작성: 2026-11-09 · 브랜치 `feature/v0.7-growth-coach` · 리비전 `0007` (down_revision `0006`)
> 프론트 연동: [frontend-integration-v0.7.md](frontend-integration-v0.7.md) · DB: [database-design.md §3.21](database-design.md)

기획 2단계: 누적 작품·승인 첨삭으로 반복 약점 분석, 성장 리포트, 맞춤 연습 과제 추천 → 강사 검토·승인 → 기존 과제로 배포.
구현하지 않음: F-15 참고작 추천, 커뮤니티, AI 직접 작품 평가, 입시 합격률 예측.

## 1. 원칙

1. **통계는 규칙 기반, AI는 설명만.** 숫자(작품 수·비율·추이)는 서버가 계산하고, Gemini는 그 결과를 문장으로 해석하거나 과제 초안을 쓸 뿐 수치를 만들지 않는다.
2. **승인된 첨삭만.** 초안·반려·대체된 첨삭, 삭제된 작품·녹음은 분석에 들어가지 않는다.
3. **AI 없이도 동작.** 통계·리포트·규칙 기반 추천은 동의·API 키·네트워크 없이 동작한다. AI는 선택 기능.
4. **자동 배포 금지.** 추천 과제는 학원 작품이면 강사가 승인·배포, 개인 작품이면 학생이 채택한다.
5. **기존 과제 시스템 재사용.** 승인된 학원 추천은 v0.3 `tasks`/`task_assignments`로 배포한다.

## 2. 반복 약점 분석 알고리즘 (`app/services/growth_analytics.py`, `growth-v1`)

입력: 범위(ALL/PERSONAL/ACADEMY)·기간·필터 안의 삭제되지 않은 작품과 그 작품의 APPROVED 첨삭 → `feedback_categories`, `feedback_items`.

| 지표 | 계산 |
| --- | --- |
| 분석 대상 작품 | 승인 첨삭이 1개 이상 있는 작품 (비율의 분모) |
| `artwork_count` | 카테고리가 지적된 **작품 수**. 한 작품에 첨삭이 여러 개거나 같은 카테고리가 반복돼도 1 |
| `mention_count` | 카테고리가 붙은 승인 첨삭 수 (첨삭 안에서는 `uq(summary_id, category)`로 이미 중복 없음) |
| `artwork_ratio` | artwork_count / 분석 대상 작품 수 |
| 반복 약점 | artwork_count ≥ 2 |
| TOP 3 | 반복 약점을 artwork_count ↓ → 최근 비율 ↓ → mention_count ↓ 순 |
| 최근 변화 | 분석 작품을 작업일순 정렬, 최근 N개(기본 5)와 그 이전 N개의 작품 단위 비율 비교. 두 구간이 모두 N개일 때만. 차이 ≥ 0.2면 MORE/LESS_FREQUENT, 아니면 SIMILAR |
| 기간별 출현 | 주/월 버킷마다 분석 작품 수와 카테고리별 작품 수 |
| 근거 | 카테고리별 최근 항목 최대 3개 (부족한 점 우선, 작품당 1개) — ID로 저장, 조회 시 현재 문장 |
| 강사가 잘한 점 | 승인 첨삭의 STRENGTH 항목, 카테고리별 작품 수 |
| 다음 학습 목표 | 반복 약점마다 고정 문장 + 최근 수정 지시(FIX) 근거 |
| 신뢰도 | 분석 작품 < 3 LOW, < 8 MEDIUM, ≥ 8 HIGH. < `GROWTH_MIN_ARTWORKS`(3)이면 INSUFFICIENT_DATA |

해석 주의 (응답 `notes`로 항상 함께 내려간다)
- AI 채점이 아니라 강사 승인 첨삭의 집계다.
- **LESS_FREQUENT는 '개선'이 아니다.** 첨삭에서 언급되지 않았을 수 있다. API·문서 어디에도 "향상" 표현을 쓰지 않는다.
- 강사마다 첨삭 방식·표현이 달라 지표가 달라질 수 있다 (같은 강사 기간 비교가 더 의미 있다).

## 3. 성장 리포트

- 생성 요청 시 통계를 **동기로 계산해 `growth_reports.metrics`에 저장**한다 (기간: WEEK 7일, MONTH 30일, ALL, CUSTOM 최대 2년, Asia/Seoul).
- **데이터 지문**(`data_fingerprint`): 승인 첨삭 ID·버전 + 작품 ID·수정 시각·완료 상태의 SHA-256. 같은 범위·기간·지문이면 같은 리포트(중복 생성 방지, 200). 조회 시 지문을 다시 계산해 `is_stale`을 알려 준다 → 재생성하면 새 리포트.
- 기록: 생성 시각, 생성자, 사용한 첨삭 ID(`source_feedback_ids`), 분석 버전, (AI) 모델·프롬프트 버전·토큰.
- AI 설명문(`narrative`)은 통계와 분리 저장·응답한다. 요청 시 조건(데이터 충분, 기능 켜짐, GROWTH_COACHING 동의)이 안 맞으면 요청 자체를 실패시키지 않고 `SKIPPED` + 사유 코드.
- 데이터 부족: `status=INSUFFICIENT_DATA`, "분석에 필요한 기록이 부족합니다." — 억지로 만들지 않는다.
- 삭제 반영: 녹음·작품이 삭제되면 근거 문장은 조회 시 자동으로 빠지고(ID만 저장), 그 첨삭을 쓴 리포트의 AI 설명문은 지워진다(`INVALIDATED`, GIN 인덱스로 탐색). 집계 숫자는 생성 시점 스냅샷으로 남고 `is_stale=true`가 된다.

## 4. 맞춤 연습 과제 추천

| | 규칙 기반 (`RULE`) | AI (`AI`) |
| --- | --- | --- |
| 실행 | API 요청 안에서 즉시 | Worker 비동기 (`PRACTICE_RECOMMEND` 작업) |
| 내용 | 카테고리별 템플릿 (`practice-template-v1`, 10개 카테고리) | Gemini가 근거 문장을 보고 작성 |
| 근거 | 반복 약점 통계의 실제 첨삭 항목 | 프롬프트의 근거 번호 `[E1]…` → 항목 ID |
| 동의 | 불필요 (외부 전송 없음) | GROWTH_COACHING |
| 검증 | — | JSON 스키마 + Pydantic, 요청한 카테고리만, 카테고리당 1개, **근거가 그 카테고리 문장을 가리켜야 함**, 수치·합격 표현 금지 → 하나도 남지 않으면 재시도 |

- 대상: 반복 약점 TOP N (`GROWTH_MAX_RECOMMENDATIONS`, 기본 3). 반복 약점이 없거나 데이터가 부족하면 409 `INSUFFICIENT_DATA`.
- 중복 방지: `batch_key` = SHA-256(범위, 출처, 데이터 지문, 분석 버전). 같은 키의 살아 있는 추천이 있으면 그대로 반환. DB 부분 유니크 `(owner_id, batch_key, weakness_category)`로 동시 요청도 막는다. AI 작업은 `dedupe_key`로 진행 중 작업 1개.
- 새 데이터로 생성하면 같은 범위의 검토 전 추천(DRAFT/IN_REVIEW)은 SUPERSEDED.
- 원본 보존: `origin_output`(템플릿 또는 AI 응답) + 현재 값(검토자 수정) + 이력(`practice_recommendation_history`, 변경 전후).
- 저장되는 분석 근거(`analysis_snapshot`): 분석 버전·기간, 분석 작품 수, 지적 작품 수, 최근 비율, 추이, 실기 유형·작업 목적 분포, 최근 작품 ID → F-15 연계용.

### 4.1 기존 과제 시스템 재사용

- v0.3 `tasks`는 `academy_id`·`class_id`가 필수다 → **학원 추천만** 과제로 배포한다. `TaskService.create`에 `before_commit` 훅을 추가해, 과제 생성과 추천의 `DISTRIBUTED`·`task_id` 연결을 **한 트랜잭션**으로 저장한다 (중복 배포 방지: 추천 행 잠금 + 상태 검사).
- 대상: `target_type=STUDENTS`, 그 학생 1명. 반은 학생이 배정된 ACTIVE 반 중 강사가 관리하는 반 (1개면 자동, 아니면 `class_id` 필요).
- 학생 완료 기록은 기존 `task_assignments.completed_at` (기존 완료 API). 추천 응답의 `task.completed`가 이를 보여 준다.
- 개인 작품 추천은 반·학원이 없어 과제를 만들 수 없으므로 추천 자체에 `ADOPTED → COMPLETED`(`completed_at`)만 둔다. 별도 과제 테이블을 만들지 않았다.

## 5. 동의 · 개인정보

- **v0.6 동의는 '첨삭 전사문 요약' 목적**이었다. 성장 분석(누적 기록 기반 프로파일링)·과제 생성은 목적이 다르므로 같은 동의로 처리하지 않고 **목적별 동의**로 확장했다: `ai_processing_consents.purpose` = `FEEDBACK_SUMMARY` | `GROWTH_COACHING`, 목적별 버전(`AI_GROWTH_CONSENT_VERSION`).
- 외부 전송 최소화: 카테고리 통계 + 승인된 첨삭 문장(최대 15개)만. 작품 제목·이름·학원·사용자 ID 미전송. 첨삭 문장 안의 고유명사는 포함될 수 있음 → 고지.
- 철회: 목적별 대기·처리 중 작업 취소, 대기 중 리포트 설명문 SKIPPED, Worker는 호출 전·저장 직전에 재확인 (이미 전송된 요청은 회수 불가).
- 타 학생 데이터: 모든 조회가 `owner_id` + 범위 조건이고 근거 해석도 같은 조건으로 다시 걸러진다. 강사는 담당 학생의 그 학원 작품만.
- 접근 기록: 리포트·약점·이력 조회 시 viewer(학생 본인/강사 소속 ID)·대상 학생 ID·대상 리포트 ID를 구조화 로그로 남긴다 (내용은 남기지 않음). 감사 테이블은 운영 요구가 확정되면 추가.
- **법적 검토 대상(미결)**: 미성년자 프로파일링 성격의 분석에 대한 동의 수준(법정대리인 확인 절차), 국외 이전 고지, 성장 리포트 보관 기간, 학원(강사)이 학생 리포트를 생성·열람하는 근거.

## 6. Gemini 호출·비용 (실제 호출 없음, 모두 Mock 테스트)

모델 `gemini-3.1-flash-lite` ($0.25 / $1.50 per 1M tokens, 2026-11 기준). 프롬프트 `growth-narrative-v1`, `practice-recommend-v1`.

| 호출 | 입력(추정) | 출력(추정) | 1회 비용 |
| --- | --- | --- | --- |
| 리포트 설명문 | 통계 + 근거 15문장 ≈ 1,500 토큰 | ≈ 600 토큰 | ≈ $0.0013 |
| AI 연습 과제 (3개) | ≈ 1,500 토큰 | ≈ 1,200 토큰 | ≈ $0.0022 |

학생 100명 × 월 4회 리포트 + 월 2회 AI 추천 ≈ 월 $1 미만 (재시도 최대 3배). 작업별 `api_call_count`·토큰이 기록된다. 서버 추가 비용 없음 (기존 Worker가 처리, 통계는 API에서 수 ms~수십 ms 쿼리).

## 7. F-15 참고작 추천 연계 (v0.8, 미구현)

v0.7이 준비한 구조:
- 약점 카테고리·근거: `feedback_categories`(첨삭 단위), `feedback_items.category`·`evidence_segment_ids`(문장 단위), 추천의 `evidence_item_ids`.
- 실기 유형·작품 분류: `artworks.practical_type`, `work_category`, 추천·리포트의 분포 스냅샷.
- 학생 최근 이력·분석 기간: `analysis_snapshot.recent_artwork_ids`, 리포트 `period_*`·`source_feedback_ids`.
- "잘 해결한 작품" 후보 신호(설계 메모): 같은 카테고리가 STRENGTH로 언급된 승인 첨삭이 있는 COMPLETED 작품. 단 **다른 학생의 작품은 작품별 공개·참고작 사용 동의가 있을 때만** 후보가 될 수 있으며, 그 동의 구조는 v0.8에서 설계한다 (v0.5.1 설계 메모 §8).

## 8. 운영

- 마이그레이션 `0007`은 승인 후 개발 DB에 적용 (현재 개발 DB는 `0004`). `0005`·`0006`·`0007`을 순서대로.
- API 서버: `GROWTH_AI_ENABLED`(기본 false). Worker: 같은 값 + `GEMINI_API_KEY`(유료 등급). 꺼져 있어도 통계·규칙 추천은 동작.
- 첫 실제 호출은 승인된 테스트 계정·테스트 첨삭으로 1회 확인 후 공개.

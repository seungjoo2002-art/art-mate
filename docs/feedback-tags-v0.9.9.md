# v0.9.9 AI 첨삭 구조화 — 분류 태그

> 작성: 2026-11-16 · 브랜치 `feature/v0.9.9-feedback-tags`

## 1. 이미 있던 구조 (v0.6~v0.9, 변경 없음)

AI 요약 호출 **1회**의 Structured Output에 요약과 구조화 결과가 함께 들어 있고, 근거 대조를 통과한 항목만 저장된다.

| 요청 항목 | 기존 구현 | 저장 위치 |
| --- | --- | --- |
| summary | `summary` | `feedback_summaries.summary` |
| strengths (잘한 점) | `strengths` | `feedback_items` kind=`STRENGTH` |
| improvements (개선할 점) | `weaknesses` + `fixes`(수정 방법) | kind=`WEAKNESS`, `FIX` |
| action_items (연습 과제) | `next_tips` | kind=`NEXT_TIP` |
| 항목별 분류 | 항목마다 `category` (`WeaknessCategory` 11개) | `feedback_items.category` |
| 약점 카테고리 | `weakness_categories` | `feedback_categories` (v0.7 성장 분석 키) |
| 근거 | 항목마다 원문 구간 번호, 원문과 표현을 공유하지 않으면 버림 | `feedback_items.evidence_segment_ids`, `dropped_item_count` |
| 내용 부족 | `insufficient_content` → 항목 없음 | `feedback_summaries.ai_output` |
| 학생·첨삭·모델·버전·시각 | — | `feedback_summaries.owner_id / recording_id·note_id / model_name / prompt_version / created_at` |

JSON 스키마(strict) 검증 실패·근거 없는 항목·잘못된 응답은 기존 `parse_output`/`InvalidAiOutput`(재시도)로 처리한다.

## 2. 이번에 추가한 것 — 분류 태그 `tags`

**문제 (운영 확인, 2026-11-16)**: 학생 화면의 칩은 약점 카테고리만 보여서, 잘한 점(예: 구도)이나 연습 과제(예: 형태)로만 언급된 주제는 태그에 나오지 않았다.

**변경**: `GET /feedbacks/{id}` 응답에 `tags`를 **추가** (계산 필드, 저장·마이그레이션 없음).

- 저장된 모든 항목(잘한 점·부족한 점·수정 방법·연습 과제)의 카테고리 + 기존 약점 카테고리를 9개 표시 태그로 묶는다.
- 근거 대조를 통과해 저장된 항목만 쓰므로 AI가 원문에 없는 태그를 만들 수 없다. 사람이 수정·삭제한 항목도 즉시 반영된다.
- `needs_work`: 부족한 점·수정 방법 또는 약점 카테고리에 나온 주제 (화면에서 주황색).
- 기존 `categories`(약점 카테고리)·성장 분석·반복 약점은 그대로.

| 태그 (`FeedbackTag`) | 라벨 | 포함 카테고리 |
| --- | --- | --- |
| COMPOSITION | 구도 | COMPOSITION |
| FORM_PROPORTION | 형태·비례 | FORM, PROPORTION |
| VALUE | 명암 | VALUE |
| COLOR | 색채 | COLOR |
| PERSPECTIVE_SPACE | 원근·공간감 | PERSPECTIVE |
| TEXTURE_EXPRESSION | 질감·표현 | TEXTURE, RENDERING |
| FINISH | 완성도 | FINISH |
| TIME_MANAGEMENT | 시간 관리 | TIME_MANAGEMENT |
| OTHER | 기타 | OTHER |

`WeaknessCategory`(11개)는 성장 분석·참고작 추천 키라 값을 바꾸지 않고, 표시 단위만 묶었다.

## 3. 영향

- DB 마이그레이션: 없음 (Alembic 0015 유지)
- AI 호출·프롬프트·비용: 변경 없음 (요약 1회에 이미 포함)
- API: 응답 필드 추가만 (하위 호환). 프론트는 `tags`가 없으면 기존 `categories`로 표시
- 기존 완료된 요약: 저장된 항목에서 계산되므로 바로 태그가 보인다

## 4. 다음 버전과의 연계

- 성장 분석: `tags`/항목 카테고리를 잘한 점 추세(강점)까지 넓혀 집계할 수 있다 (현재는 약점만).
- 이미지 평가·RAG·합격작 비교(이후 버전)는 같은 9개 태그를 공통 축으로 쓸 수 있다.

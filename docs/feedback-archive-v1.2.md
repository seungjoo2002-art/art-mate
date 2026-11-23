# v1.2 첨삭 정리·성장 아카이브·홈 브리핑 (12월 8일 발표 대비)

> 작성: 2026-11-23 · 브랜치 `feature/v1.2-feedback-archive-briefing` (main `1b49256` 기준)
> DB 마이그레이션 **없음** (Alembic 0016 유지) · 새 유료 API **없음** · 프론트엔드 변경 **없음**

## 0. 한 줄 요약

학생이 남긴 강사 첨삭(텍스트·음성)을 **기존 파이프라인 그대로** 정리·확정하고, 이번에 다음을 더했다.

1. STT: 미술 용어 힌트(faster-whisper) + **AI 문맥 보정**(원문 보존, 의미 변경은 서버가 거절)
2. 아카이브: **개선 추세**(지적 → 이후 실제 칭찬), **실제 칭찬 기반 강점**, **세부 주제로 묶은 반복 실수**(예: "타원"·"원통 윗면" → 타원·원통형 형태)
3. API 2개: `GET /growth/me/briefing`(홈 오늘의 브리핑), `GET /growth/me/analysis-report`(아카이브 분석 리포트) — **조회 때 LLM 호출 없음**

## 1. 조사 결과 — 기존 구현 상태

| 요구 | 기존 구현 (재사용) | 이번 변경 |
| --- | --- | --- |
| 새 작품 기록 / 실기시험 모드 | 같은 `artworks` 표. 시험은 `work_category=MOCK_EXAM` + `time_limit_minutes` + 타이머 이벤트. 사용자 지정 단계(`artwork_stages`, 0~10개, 단계 없이 완성작만 가능, v0.9.7) | 없음 (구조가 이미 공유됨) |
| 단계별·작품 전체 첨삭 | `feedback_notes.stage_id` / `feedback_recordings.stage_id` (NULL = 작품 전체) | 없음 |
| 텍스트·음성 첨삭 → 같은 AI 정리 | 텍스트 `feedback_notes` → 문장 구간, 음성 `feedback_recordings` → `feedback_transcripts` 구간. 둘 다 `SUMMARIZE` 작업 → 같은 출력 스키마·검증 | 녹음 쪽에 문맥 보정 단계 추가 |
| AI 첨삭 구조화 | `feedback_summaries`(요약, AI 원본 `ai_output` 불변) + `feedback_items`(STRENGTH/WEAKNESS/FIX/NEXT_TIP, 카테고리, **근거 구간 번호**) + 근거 대조(원문과 표현이 겹치지 않으면 버림) | 없음 (요구 항목과 1:1 대응, §5) |
| 학생 수정·확정 | `PATCH /feedbacks/{id}`, `approve`, `reopen`, 이력 `feedback_review_history` | 없음 |
| 작업 큐·재시도·중복 방지 | `ai_processing_jobs` (lease, 최대 3회, 부분 유니크 인덱스), GitHub Actions Worker | 없음 |
| 동의·미성년자 정책 | `ai_processing_consents` (목적별, 14세 미만 차단, 보호자 확인), `AI_PROVIDER_TERMS_CONFIRMED` 게이트, 전송 전 이름·연락처 가림 | 문맥 보정도 같은 동의(FEEDBACK_SUMMARY)·같은 가림 사본 사용 |
| 성장 분석 | 규칙 기반 통계(v0.7~v1.0, 9개 태그), 리포트 + AI 설명문(데이터 지문 dedupe) | 개선 추세·강점·세부 주제 판정, 설명문 프롬프트 v2 |
| 홈 브리핑 | 없음 | 새 API |
| Claude Vision 작품 평가 | **코드 없음.** `docs/ai-review-v1.2-plan.md`(커밋되지 않은 계획 문서)만 있음 | 구현하지 않음 (초기 서비스에서 제외 결정). 비활성화할 코드가 없으므로 삭제·분리 작업도 없음. v1.1 `comparison_input.py`(순수 함수)는 모의고사 통합 때 쓸 수 있어 그대로 둠 |

손대지 않은 것: 프론트엔드, ArtCLIP·모의고사 관련 파일, Alembic, 기존 API 응답 형식(필드 **추가**만).

## 2. 데이터 흐름

```text
텍스트 첨삭 POST /artworks/{id}/feedback-notes ───────────────┐
음성 첨삭  POST /artworks/{id}/recordings → 업로드 → 전사(서버 STT 또는 기기 STT) │
          └ (v1.2) 요약 작업 안에서: 문맥 보정 → 보정 전사 새 행 저장 ──────┤
                                                               ▼
                       SUMMARIZE (같은 프롬프트·스키마·근거 검증) → feedback_summaries(DRAFT)
                                                               ▼
                       학생 확인·수정 → 확정(APPROVED)  ← 확정분만 분석에 들어간다
                                                               ▼
        GET /growth/me/analysis-report · GET /growth/me/briefing (매 조회 시 DB에서 다시 계산, LLM 없음)
                                                               ▼ (선택, 비동기)
        성장 리포트 AI 설명문 (GROWTH_REPORT 작업, 같은 데이터면 1번만) → 브리핑·리포트의 ai_comment
```

원본 보존: 첨삭 원문(`feedback_notes.body`, 전사 원본 행)은 AI 처리 실패와 무관하게 저장된다. AI 결과는 별도 표에 저장되고 원문을 바꾸지 않는다.

## 3. STT 정확도 개선

### 3.1 현재 구조 (조사)

| 항목 | 값 |
| --- | --- |
| 제공자 | 서버: faster-whisper(로컬 실행, 외부 전송 없음, GitHub Actions Worker). 기기: 브라우저 Whisper(`browser-*`) |
| 모델 | `STT_MODEL` 기본 `small` (int8, beam 1) |
| 파일 | 비공개 버킷, Signed URL 업로드 → Worker가 Signed URL로 내려받음 |
| 길이 제한 | `STT_MAX_AUDIO_SECONDS` 1200초, 처리 제한 `STT_TIMEOUT_SECONDS` |
| 저장 | `feedback_transcripts`(불변 행). 학생 수정은 새 행(`edited_from_id`) |
| 오류 | `SttError(code, retryable)` → 작업 오류 코드, 재시도 최대 3회, 학생 재시도 API |
| 단어별 신뢰도 | 저장하지 않음. 이번에도 **만들지 않는다** |

기존 엔진은 잘 동작하므로 교체하지 않았다.

### 3.2 미술 용어 힌트 (추가 비용 없음)

- `app/services/art_glossary.py`의 용어 27개(요청 목록 전부)를 faster-whisper `hotwords`로, 상황 설명 한 문장을 `initial_prompt`로 넘긴다.
- **설치된 버전이 받는 인자만** 넘긴다 (`inspect.signature` 확인). 잠금 버전 1.2.1은 둘 다 지원한다.
- `initial_prompt`에 용어를 나열하지 않는다: 무음 구간에 프롬프트가 그대로 출력되는 Whisper 환각을 피하기 위해.
- 끄기: `STT_VOCABULARY_HINTS=false`.
- 기기(브라우저) STT에는 힌트 기능이 없어 적용하지 않는다 → 아래 문맥 보정으로 보완.

### 3.3 문맥 보정 (`app/services/stt_correction.py`)

녹음 첨삭을 요약하기 직전, 같은 Worker 작업 안에서 LLM을 1번 더 호출해 오인식만 고친다.

| 원칙 | 구현 |
| --- | --- |
| 원본 보존 | 원본 전사 행은 그대로. 보정본은 새 행 (`engine=ai-context-correction`, `edited_from_id`=원본) |
| 별도 저장·차이 확인 | `GET …/transcript`에 `stt_original`(원문 구간, 현재와 다른 구간 번호)·`ai_correction`(AI가 바꾼 구간 번호, 안내 문구) 추가 |
| 학생이 수정 가능 | 기존 `PUT …/transcript` 그대로. 수정 후에도 원문 비교·AI 보정 정보가 따라온다 |
| 의미 변경 금지 | 프롬프트 규칙 + **서버 구간별 검사** (하나라도 어기면 그 구간은 원문 유지): 글자 유사도 ≥ 0.6, 길이 변화 ≤ max(4자, 25%), 부정 표현(안·않·못·없·아니·말고) 개수 동일, 숫자 동일, 새 단어는 원문의 비슷한 단어를 고친 것이어야 함 |
| 추측 금지 | 위 검사로 "어 그 부분 음 좀" → "그 부분 명암 대비를 높여" 같은 채워 넣기를 거절 (테스트 포함) |
| 구간 1:1 | 번호·시각·개수 그대로 → 요약 근거 번호가 그대로 맞는다 |
| 개인정보 | 가림 사본(이름·연락처 → `[학생]` 등)만 전송. 가림이 들어간 구간은 보정하지 않음 |
| 사람이 쓴 글 우선 | 학생이 고친 전사, 이미 보정된 전사는 다시 보정하지 않음 |
| 실패해도 계속 | LLM 오류·형식 오류면 보정을 건너뛰고 원본 전사로 요약 (작업은 실패하지 않음) |
| 원자성 | 보정본은 요약과 **같은 트랜잭션**에 저장 → 요약이 실패·취소되면 보정본도 남지 않음 |
| 녹음 재확인 아님 | 응답 `ai_correction.notice`: "녹음을 다시 듣고 확인한 것은 아니에요" |
| 이전 첨삭 문맥 | **쓰지 않음** (현재 발언에 없는 내용이 섞일 위험). 용어 사전만 참고 |

비용: 요약 1건당 LLM 호출 +1 (입력 ≈ 전사 길이 + 규칙 ~500토큰, 출력은 바뀐 구간만). gpt/gemini flash-lite급 기준 1건 약 $0.001 미만 추정 — **실측 필요**. 호출 수·토큰은 기존처럼 `ai_processing_jobs.api_call_count/input_tokens/output_tokens`에 누적된다. 끄기: `STT_CONTEXT_CORRECTION_ENABLED=false`.

## 4. AI 첨삭 구조화 — 요구 항목 대응 (기존 v0.6~v0.9.9, 변경 없음)

| 요구 | 저장 위치 |
| --- | --- |
| 핵심 요약 | `feedback_summaries.summary` (AI 원본은 `ai_output`에 불변 보관) |
| 잘한 점 / 부족한 점 / 구체적 수정 지시 / 다음 연습 권장 | `feedback_items.kind` = STRENGTH / WEAKNESS / FIX / NEXT_TIP |
| 관련 평가 영역 (여러 개) | 항목마다 `category` + 첨삭별 `feedback_categories` + 응답 `tags`(9개 표시 태그) |
| 근거 원문 구간 | `feedback_items.evidence_segment_ids` → 응답 `source_text` |
| 입력에 없는 내용 금지 | 프롬프트 규칙 + 근거 번호 필수 + 원문 표현 대조, 버린 수 `dropped_item_count` |
| 모호·짧은 첨삭 | `insufficient_content=true` → 항목 비움 |
| 학생 입력과 AI 정리 분리 | 원문(`feedback_notes.body`/전사)과 정리 결과(별도 표), 항목 `origin` = AI/EDITED/ADDED |
| 학생 수정 | `PATCH /feedbacks/{id}` (낙관적 잠금 `version`) |

평가 영역 대응 (요청 8개 → 기존 카테고리, 값은 성장 분석 키라 바꾸지 않음):
형태 `FORM` · 비례 `PROPORTION` · 구도 `COMPOSITION` · 명암 `VALUE` · 색채 `COLOR` · 재질·질감 `TEXTURE`(+`RENDERING`) · 공간·원근 `PERSPECTIVE` · 기타 `OTHER` (+ 기존 `FINISH`, `TIME_MANAGEMENT`).

## 5. 아카이브 성장 분석 규칙 (`app/services/growth_insights.py`)

- 대상: **확정된 강사 첨삭**(source=INSTRUCTOR)만. 자기 메모·다른 학생 의견은 분석에 넣지 않는다 (v0.9 원칙 유지).
- 단위: 작품 1개 = 태그(영역)마다 사건 1개. 그 작품 첨삭에서 지적(WEAKNESS/FIX·약점 카테고리) = NEG, 잘한 점 = POS, 둘 다 = MIXED.

| 분석 | 규칙 | 근거로 내려 주는 것 |
| --- | --- | --- |
| 반복 실수 | 지적이 나온 작품 ≥ 2 | 작품 수, 마지막 지적일, 관련 작품 목록, 최근 지적 항목(작품당 1개, 최대 3) |
| 세부 주제 | 지적 항목 문장에 같은 주제 키워드(예: 타원·원통·입구·윗면)가 있는 작품 ≥ 2. 키워드가 없으면 묶지 않음 | 주제 라벨, 작품 수, 근거 항목 |
| 강점 | **잘한 점 항목**이 나온 작품 ≥ 2 (지적이 없다는 이유로는 강점 아님) | 최근 긍정 항목 |
| 개선 추세 IMPROVING | 작업일 순으로 지적이 먼저 있고, 마지막 지적 **이후 작품이 모두 긍정**. 이후 긍정 ≥ 2이면 `improvement_confirmed` | 첫 지적일, 마지막 긍정일, 사건 목록(NEG/POS/MIXED) |
| 여전히 개선 필요 NEEDS_WORK | 가장 최근 사건이 지적(또는 칭찬+지적) | 최근 지적·수정 방법 |
| 판단 보류 INSUFFICIENT | 그 영역 사건이 1개뿐 등 | — |

- 의미가 비슷한 지적 연결은 **용어 주제 사전**으로 한다(결정적, 테스트 가능). LLM으로 묶지 않은 이유: 관련 없는 첨삭을 무리하게 묶을 위험, 비용, 재현성. 사전에 없는 표현은 같은 태그 안에서만 집계된다.
- 점수·성장률·백분율은 만들지 않는다. 숫자는 실제 작품 수·날짜뿐이다.

### 5.1 최소 데이터 기준

| 기준 | 값 | 이유 |
| --- | --- | --- |
| 전체 분석(반복 실수·강점·추세) | 확정 강사 첨삭이 있는 작품 ≥ `GROWTH_MIN_ARTWORKS`(기본 3) | 기존 성장 리포트와 같은 기준 (v0.7부터 운영) |
| 그 미만 | `INSUFFICIENT_DATA`: 최근 첨삭 요약·가장 최근 지적 1개만 보여 주고 목록은 비움 | 무리한 분석 방지 |
| 반복·강점·세부 주제 | 작품 2개 이상 | 같은 작품 안의 중복은 1번으로 셈 |
| 개선 확인 | 지적 뒤 긍정 작품 2개 이상 (1개는 초기 신호) | 우연한 1회 칭찬과 구분 |

## 6. 홈 오늘의 브리핑 (`app/services/growth_briefing.py`)

**조회 때 LLM을 부르지 않는다.** 문장은 규칙으로 만들고, 첨삭 내용은 확정된 실제 항목 문장을 그대로 인용한다.

| 상태 | 조건 | 문장 |
| --- | --- | --- |
| `NO_RECORDS` | 작품·첨삭 없음 | "아직 첨삭 기록이 없어요. 첫 작품을 등록하고 선생님의 피드백을 기록해 보세요!" |
| `NO_FEEDBACK` | 작품은 있으나 확정 강사 첨삭 없음 | "아직 첨삭 기록이 없어요. 작품에 선생님의 피드백을 기록해 보세요!" (자기 메모만 있으면 안내 추가) |
| `PROCESSING` | 전사·정리 작업 진행 중 | "첨삭을 정리하고 있어요. 잠시 후 다시 확인해 주세요." |
| `NEEDS_CONFIRMATION` | 정리 끝, 확정 전 | "AI가 정리한 첨삭 N건이 확인을 기다리고 있어요." |
| `INSUFFICIENT_DATA` | 확정 작품 < 3 | 가장 최근 지적/칭찬 1개 + "아직 성장 추세를 분석할 만큼…" |
| `READY` | 확정 작품 ≥ 3 | 예: "최근 타원·원통형 형태에 대한 첨삭이 3개 작품에서 반복되고 있어요." / "명암 부분은 이전 지적 이후 좋아졌다는 첨삭이 이어지고 있어요." / "오늘은 이 첨삭을 떠올리며 연습해 보세요: “타원 형태를 다시 확인해라.”" |

AI 코멘트(`ai_comment`)는 기존 성장 리포트의 저장된 설명문만 읽는다.

- 현재 데이터 지문과 같으면 `READY`, 다르면 이전 설명문을 `STALE`(based_on_current_data=false)로 함께 준다 → "처리 중에는 이전 결과 표시".
- 데이터가 바뀌었고 성장 AI가 켜져 있고 학생의 GROWTH_COACHING 동의가 있으면, 브리핑 조회 때 **설명문 생성을 1번 요청**한다 (`PENDING`). 같은 데이터는 리포트 dedupe로 1번, 최소 간격 `GROWTH_BRIEFING_REFRESH_MINUTES`(기본 360분), 알림은 보내지 않는다. 끄기: `GROWTH_BRIEFING_AUTO_REFRESH=false`.
- 설명문 프롬프트 v2(`growth-narrative-v2`): 규칙 판정 블록을 넣고 "좋아지고 있다"는 [개선 근거 있음] 영역에만 쓰게 했다. 기존 금지 표현 검사(백분율·점수·합격 등)는 그대로.

## 7. 데이터 일관성

분석·브리핑은 저장된 스냅샷이 아니라 **매 조회 시 현재 확정 첨삭으로 계산**하므로 오래된 분석이 최신처럼 보이지 않는다. 응답의 `data_fingerprint`(확정 첨삭 id·version + 작품 updated_at의 해시)로 같은 데이터인지 알 수 있다.

| 이벤트 | 반영 |
| --- | --- |
| 첨삭 생성·확정 | 확정 즉시 분석 포함 |
| 첨삭 수정 | 확정본은 `reopen` 후 수정 → 확정 취소 즉시 분석에서 빠지고, 다시 확정하면 새 내용으로 들어감 |
| 첨삭 삭제 / 작품 삭제 | 행 삭제·소프트 삭제 → 즉시 제외 (근거 문장도 조회 시 사라짐) |
| STT 재변환·보정 수정 | 전사 수정 시 기존 초안 대체(SUPERSEDED)·진행 작업 취소 (기존). 확정본은 잠금(`TRANSCRIPT_LOCKED`) |
| 단계 삭제·변경 | 첨삭은 작품 단위로 집계 → 영향 없음 |
| AI 설명문 | 데이터 지문이 다르면 STALE 표시, 필요 시 1번 재요청 |
| 중복 분석·재시도 | 기존 작업 큐 부분 유니크 인덱스·리포트 dedupe·최대 3회 재시도 |
| LLM 실패 | 원문 보존, 작업 FAILED → 학생 재시도 API(기존) |

## 8. API 명세 (프론트엔드 연결용)

공통: `Authorization: Bearer <Supabase access token>`, 학생 계정. 오류 형식 `{"error": {"code", "message", "details"}}`. 로그인 없음 401 `UNAUTHORIZED`, 학생이 아님 403 `FORBIDDEN`, 남의 리소스 404 `NOT_FOUND`. 모든 `/growth/me/*`는 본인 데이터만.

### 8.1 새 API

#### `GET /api/v1/growth/me/briefing` — 홈 오늘의 브리핑

```json
{
  "status": "READY",
  "headline": "최근 타원·원통형 형태에 대한 첨삭이 3개 작품에서 반복되고 있어요.",
  "lines": [
    "명암 부분은 이전 지적 이후 좋아졌다는 첨삭이 이어지고 있어요.",
    "오늘은 이 첨삭을 떠올리며 연습해 보세요: “타원 형태를 다시 확인해라.”",
    "확정을 기다리는 첨삭이 1건 있어요. 확정하면 분석에 반영돼요."
  ],
  "focus": {"tag": "FORM_PROPORTION", "label": "형태·비례", "theme_label": "타원·원통형 형태", "reason": "REPEATED", "artwork_count": 3},
  "highlight": {"tag": "VALUE", "label": "명암", "kind": "IMPROVING", "artwork_count": 2},
  "practice": { "...Evidence": "아래 참고" },
  "evidence": [ { "...Evidence": "" } ],
  "counts": {
    "artwork_count": 6, "completed_artwork_count": 6, "mock_exam_count": 1, "practice_artwork_count": 5,
    "confirmed_feedback_count": 6, "instructor_feedback_count": 6, "analyzed_artwork_count": 6,
    "pending_review_count": 1, "processing_count": 0, "last_feedback_date": "2026-11-18"
  },
  "ai_comment": {"status": "STALE", "report_id": "…", "overview": "…", "strengths_comment": "…", "improvement_comment": "…", "based_on_current_data": false, "generated_at": "…", "reason": null},
  "data_fingerprint": "9f2c…",
  "generated_at": "2026-11-23T09:00:00Z"
}
```

- `status`: `NO_RECORDS` · `NO_FEEDBACK` · `PROCESSING` · `NEEDS_CONFIRMATION` · `INSUFFICIENT_DATA` · `READY` (§6).
- 화면: `headline` + `lines`를 그대로 보여 주면 된다. `focus`/`highlight`/`practice`는 강조·링크용(없으면 null).
- `ai_comment.status`: `READY`(현재 데이터) · `STALE`(이전 데이터 — "이전 분석" 표시 권장) · `PENDING`(갱신 중 — 이전 내용이 있으면 함께 옴) · `FAILED` · `NOT_AVAILABLE`(AI 꺼짐·데이터 부족) · `NONE`.
- 홈 진입마다 호출해도 된다 (DB 조회만). `PENDING`이면 30~60초 뒤 다시 조회.

`Evidence` (기존 성장 API와 같은 형식):

```json
{
  "item_id": "…", "feedback_id": "…", "recording_id": null, "note_id": "…", "source": "INSTRUCTOR",
  "artwork_id": "…", "artwork_title": "정물 소묘", "work_date": "2026-11-15",
  "kind": "FIX", "category": "FORM", "content": "타원 형태를 다시 확인해라.",
  "start_ms": null, "source_text": ["타원 형태 다시 확인해."]
}
```

`kind`: STRENGTH(잘한 점)·WEAKNESS(부족한 점)·FIX(수정 지시)·NEXT_TIP(다음 연습). 녹음 첨삭이면 `recording_id`·`start_ms`(재생 위치).

#### `GET /api/v1/growth/me/analysis-report` — 아카이브 분석 리포트

| 필드 | 화면 섹션 |
| --- | --- |
| `status`, `message` | `NO_FEEDBACK` · `NEEDS_CONFIRMATION` · `INSUFFICIENT_DATA`(message에 안내 문구) · `READY` |
| `counts` | 1. 전체 학습 기록 (단순 기록 수 — AI 분석 아님) |
| `recent_feedbacks[]` | 2. 최근 첨삭 요약 (`summary`, `tags`, 작품·날짜) |
| `repeated_mistakes[]` | 3. 반복 지적 영역 (`themes`, `issue_artwork_count`, `last_issue_date`, `related_artworks`, `issue_evidence`) |
| `strengths[]` | 4. 긍정 평가가 많은 영역 (`positive_artwork_count`, `positive_evidence`) |
| `improving[]` | 5. 개선되고 있는 영역 (`improvement_confirmed`, `first_issue_date`, `last_positive_date`, `events`) |
| `needs_work[]` | 6. 여전히 개선이 필요한 영역 |
| `next_practice[]` | 7. 다음 연습 추천 (실제 첨삭의 NEXT_TIP, 최근 5개) — 기존 `POST /growth/me/practice-tips/{item_id}/task`로 과제 담기 |
| 각 항목의 `*_evidence`, `related_artworks` | 8. 근거 첨삭·작품 |
| `tags[]` | 언급된 모든 영역 (차트용, `events` = 날짜별 NEG/POS/MIXED) |
| `ai_narrative` | 저장된 AI 설명문 (브리핑의 `ai_comment`와 같은 형식, 이 API는 갱신 요청을 하지 않음) |
| `criteria`, `notes` | 판정 기준·해석 주의 (화면 하단 안내용) |

`TagInsight` 예:

```json
{
  "tag": "VALUE", "label": "명암", "progress": "IMPROVING",
  "issue_artwork_count": 1, "positive_artwork_count": 2,
  "first_issue_date": "2026-11-01", "last_issue_date": "2026-11-01", "last_positive_date": "2026-11-18",
  "positive_since_last_issue": 2, "improvement_confirmed": true,
  "themes": [], "issue_evidence": [], "positive_evidence": [], "practice_evidence": [],
  "related_artworks": [{"id": "…", "title": "컵 정물", "work_date": "2026-11-18"}],
  "events": [
    {"artwork_id": "…", "work_date": "2026-11-01", "polarity": "NEG"},
    {"artwork_id": "…", "work_date": "2026-11-10", "polarity": "POS"},
    {"artwork_id": "…", "work_date": "2026-11-18", "polarity": "POS"}
  ]
}
```

### 8.2 변경된 API (필드 추가만, 하위 호환)

`GET /api/v1/artworks/{artwork_id}/recordings/{recording_id}/transcript` (그리고 `PUT` 응답·기기 전사 저장 응답의 `transcript`)

| 필드 | 설명 |
| --- | --- |
| `origin` | 값 추가: `AI_CORRECTED` (기존 SERVER/BROWSER/EDITED) |
| `stt_original` | 현재 전사가 원문과 다를 때: `{transcript_id, engine, text, segments[], differs_from_current: [구간 번호]}`, 아니면 null |
| `ai_correction` | AI 보정이 적용됐을 때: `{transcript_id, model_name, changed_segments: [구간 번호], created_at, notice}`, 아니면 null |

화면 권장: 보정 구간에 표시 → 누르면 `stt_original.segments[i].text`와 비교, `notice` 표시, 기존 수정 화면(PUT)으로 고치기.

### 8.3 흐름별로 쓰는 기존 API (변경 없음)

| 기능 | API |
| --- | --- |
| 작품 기록 (자유 연습 / 실기시험) | `POST /artworks` (`work_category`: `PERSONAL_PRACTICE`·`MOCK_EXAM`, `time_limit_minutes`), 타이머 `GET /artworks/{id}/timer`·`POST /artworks/{id}/timer/events` |
| 단계 만들기·바꾸기 (0~10개, 없어도 됨) | `GET/PUT /artworks/{id}/stages` |
| 텍스트 첨삭 등록·조회·수정·삭제 | `POST/GET /artworks/{id}/feedback-notes`, `GET/PATCH/DELETE /feedback-notes/{id}` (`stage_id` = 단계, null = 작품 전체) |
| 텍스트 첨삭 AI 정리 요청 | `POST /feedback-notes/{id}/summary` (202, 동의 필요 409 `AI_CONSENT_REQUIRED`, 한도 429) |
| 음성 첨삭 | `POST /artworks/{id}/recordings` → 업로드 → `POST …/complete` |
| STT 요청·상태·재시도 | `POST/GET …/transcription`, `POST …/transcription/retry`, 기기 전사 `POST …/transcript/browser {auto_summarize}` |
| STT 원문·보정문 조회·수정 | `GET/PUT …/transcript` (§8.2) |
| 음성 첨삭 AI 정리 요청·상태·재시도 | `POST/GET …/summary`, `POST …/summary/regenerate` |
| AI 정리 결과 조회·수정·확정 | `GET/PATCH /feedbacks/{id}`, `POST /feedbacks/{id}/approve`·`reopen`·`reject`, 이력 `GET /feedbacks/{id}/history` |
| 작품별 첨삭 요약 | `GET /artworks/{id}/feedbacks` (확정분), 단계별 `GET /artworks/{id}/stage-history` |
| 분석 갱신 상태 | 브리핑 `ai_comment.status`, 설명문 작업 `GET /growth/me/jobs/{job_id}` |
| AI 기능 켜짐 여부 | `GET /meta/ai-features` |

처리 상태 값: 작업 `QUEUED`·`RUNNING`·`SUCCEEDED`·`FAILED`·`CANCELLED`, 첨삭 `DRAFT`·`IN_REVIEW`·`APPROVED`·`REJECTED`·`SUPERSEDED`.

## 9. 설정 (새 환경 변수, 모두 기본값으로 동작)

| 이름 | 기본 | 위치 | 설명 |
| --- | --- | --- | --- |
| `STT_VOCABULARY_HINTS` | true | Worker | faster-whisper 용어 힌트 |
| `STT_CONTEXT_CORRECTION_ENABLED` | true | Worker | 요약 전 문맥 보정 (요약이 켜져 있고 동의가 있을 때만 실제 호출) |
| `GROWTH_BRIEFING_AUTO_REFRESH` | true | API | 브리핑 조회 때 설명문 1회 재요청 (`GROWTH_AI_ENABLED`·동의 필요) |
| `GROWTH_BRIEFING_REFRESH_MINUTES` | 360 | API | 재요청 최소 간격 |

## 10. 테스트

실제 유료 AI 호출 없이 가짜 LLM·가짜 STT로 검증했다.

| 파일 | 내용 |
| --- | --- |
| `tests/test_v12_stt.py` (23) | 용어 힌트(지원 인자만), 요청 용어 전부 포함, 보정 허용(조사·용어·띄어쓰기·문장부호) / 거절(내용 추가, 칭찬→지적, 부정 추가·삭제(띄어쓰기 없는 "안좋아" 포함), 숫자, 추측 채우기, 빈 값), 잠금 구간, 중복·없는 번호, 형식 오류, 세부 주제 묶기 |
| `tests/test_v12_insights.py` (14) | 요청 예시 그대로: 11/3·8·15 타원 → 반복 실수 1개 주제(3작품), 11/1·10·18 명암 → 개선 확인. 관련 없는 첨삭은 묶지 않음, 칭찬 1회는 초기 신호, 최근 칭찬+지적은 개선 아님, 지적 없음 ≠ 강점, 자기 메모 제외, 데이터 부족 시 목록 비움, 브리핑 6상태·수치 생성 없음·인용은 실제 항목 |
| `tests/db/test_v12_feedback_archive.py` (6, PostgreSQL) | 녹음 → 기기 STT → 보정(의미 변경 거절) → 요약이 보정문 사용, 원본 행 보존, 비용 기록 2회, 학생 재수정 / 보정 실패 시 원본으로 요약, 학생이 고친 전사는 재보정 안 함 / 0건 → 확정 대기 → 1건 → 3건(자유 2 + 실기시험 1) 리포트·브리핑, 다른 학생 미포함, 조회 때 LLM 0회, 확정 취소·삭제 즉시 반영 / 설명문 자동 갱신 1회·알림 없음·READY·새 첨삭 후 STALE / 로그인 필요 |

## 11. 남은 문제·결정 필요

1. **실제 음성으로 검증 안 됨**: 용어 힌트·문맥 보정의 효과는 실제 학원 녹음으로 측정해야 한다 (`scripts/stt_compare.py`로 힌트 켬/끔 비교 가능). 실제 LLM 보정 품질도 미측정 — 비용 승인 후 10~20건으로 확인 권장.
2. **확정 단계**: 분석은 학생이 확정한 첨삭만 쓴다. 학생이 확정하지 않으면 아카이브가 비어 보이므로, 프론트에서 정리 결과 화면에 "확정" 버튼을 눈에 띄게 두는 것을 권장 (브리핑은 `NEEDS_CONFIRMATION`으로 안내).
3. **세부 주제 사전**: 14개 주제 키워드 사전 방식이라, 사전에 없는 표현은 태그 단위로만 묶인다. 실제 첨삭이 쌓이면 키워드를 보강한다 (`app/services/art_glossary.py`).
4. **기기(브라우저) STT**: 힌트 기능 없음 → 보정에만 의존.
5. `docs/ai-review-v1.2-plan.md`(Claude Vision 계획, 커밋 안 됨): 이번 결정으로 보류. 문서를 지우지는 않았다.
6. 모의고사(ArtCLIP) 통합: 같은 `artworks`·`feedback_*` 구조를 쓰면 이번 분석에 그대로 들어온다 (`work_category`로 구분 가능). 통합 방식은 담당 팀원과 별도 결정.

## 12. 배포 전 할 일

1. PR 리뷰·CI 통과 (마이그레이션 없음 → `check_db_revision`은 0016 그대로).
2. Render(API)·GitHub Actions(Worker) 배포. 새 설정은 기본값으로 동작하므로 추가 설정 불필요. 문맥 보정을 처음에는 끄고 싶으면 Actions Variable `STT_CONTEXT_CORRECTION_ENABLED=false`.
3. 프론트엔드 담당자에게 §8 전달 (홈 카드: `/growth/me/briefing`, 아카이브 분석 탭: `/growth/me/analysis-report`, 전사 화면: `stt_original`·`ai_correction`).
4. (선택) 실제 녹음·LLM 품질 확인 — 유료 호출이므로 승인 후.

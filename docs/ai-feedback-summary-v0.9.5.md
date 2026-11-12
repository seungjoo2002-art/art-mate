# v0.9.5 AI 첨삭 요약 활성화 — 원인·흐름·설정·정책

> 작성: 2026-11-12 · 브랜치 `feature/ai-feedback-summary-activation` (main = PR #49·#50 병합 후)
> 관련: [ai-feedback-v0.6.md](ai-feedback-v0.6.md), [stt-worker-github-actions.md](stt-worker-github-actions.md)

## 1. "AI 정리 기능이 아직 준비 중"이 뜨는 원인

요약은 **두 곳의 설정이 모두 켜져야** 동작한다. 지금은 둘 다 꺼져 있다.

| 위치 | 하는 일 | 현재 상태 (근거) |
| --- | --- | --- |
| Render API | 요약 요청을 받아 `SUMMARIZE` 작업을 큐에 넣음 (`AI_SUMMARY_ENABLED`) | 꺼짐으로 판단 — 카드 문구는 `/meta/ai-features`의 `ai_summary=false`일 때만 나온다. Render 대시보드는 직접 확인하지 못함 |
| GitHub Actions Worker | 큐의 요약 작업을 Gemini로 처리 (`AI_SUMMARY_ENABLED` 변수 + `GEMINI_API_KEY` 시크릿) | **꺼짐 (확인)** — `gh secret list`에 `WORKER_DATABASE_URL`만 있고 변수 없음. Worker 로그 `"llm": null` |
| (보조) Render `WORKER_DISPATCH_TOKEN` | 작업 생성 즉시 Worker 실행 | 미설정으로 보임 — 11-12 08:50 UTC 이후 Worker 실행 기록 없음. 없으면 요약도 예약 실행(실측 수 시간 간격)을 기다린다 |

코드는 v0.6부터 있었다: Gemini 호출(`integrations/ai/gemini.py`), 프롬프트·검증(`services/ai_summary.py`), 저장(`feedback_summaries`·`feedback_items`·근거), 검토 화면(`/feedbacks/{id}`).

## 2. 처리 흐름 (기존 구조 재사용, 새 테이블·API 없음)

```text
대본 저장 (기기 POST …/transcript/browser {auto_summarize} | 서버 전사 chain_summary)
 └ 동의 O + AI 켜짐 → SUMMARIZE 작업 생성 (params.transcript_id = 그 시점 최신 대본)   ← 대본 저장과 분리
Worker → Gemini(구조화 JSON) → 검증: 형식·근거 구간 번호·근거 문장과 표현 대조 → 근거 없는 항목 버림
 └ feedback_summaries(DRAFT) + feedback_items(STRENGTH/WEAKNESS/FIX/NEXT_TIP, 근거 구간) 저장
녹음 카드 → "AI 첨삭 정리 보기" → 전체 요약·잘한 점·개선할 점(부족한 점·수정 방법)·반복 약점·다음 작품 연습 과제
학생 확정(APPROVED) → 성장 분석(반복 약점·맞춤 과제)에 반영  ← 확정 전 초안은 성장 분석에 쓰지 않음
```

- 실패해도 대본은 그대로. 실패 작업은 "AI 분석 다시 시도"(재생성 API). 재시도 가능한 오류(429·5xx·시간 초과)는 Worker가 자동 재시도(최대 3회).
- 같은 대본 중복 호출 방지: 진행 중 작업 1개(부분 유니크), 초안이 있으면 일반 요청은 409 → 재생성은 명시적으로만. 하루 요청 한도 20건(설정).
- 대본 수정 → 초안 대체 → 다시 요청하면 **최신 대본**으로 분석.
- 화면 이동·새로고침: 작업·결과는 DB에 있으므로 상태 API로 복원.

## 3. 이번 변경

| 영역 | 내용 |
| --- | --- |
| 운영 전송 차단 | 배포 환경(staging/production)에서는 `AI_PROVIDER_TERMS_CONFIRMED=true`가 있어야 `AI_SUMMARY_ENABLED`·`GROWTH_AI_ENABLED`가 실제로 켜진다 (API·Worker 공통 `ai_summary_active`). 없으면 요약 요청 503, Worker는 Gemini 클라이언트를 만들지 않음 |
| 상태 API | `/meta/ai-features`에 `ai_summary_status`: `ENABLED` / `DISABLED` / `TERMS_UNCONFIRMED` (키·설정값 노출 없음) |
| 자동 요약 | 녹음 카드에서 "녹음을 글로 바꾸기"를 해도 동의가 있으면 대본 완성 시 요약까지 자동 요청 (녹음 화면 저장은 기존에도 자동) |
| 카드 상태 | 대본 생성 중 / 대본 완료(대본 보기) / **AI 사용 동의 필요**(동의 화면 이동) / **AI 서비스 설정 필요** / AI 첨삭 분석 중 / **AI 첨삭 정리 보기** / AI 분석 다시 시도 |
| 프롬프트 v3 | next_tips = "다음 작품에서 실천할 연습 과제"(강사가 말한 경우만), 학생 눈높이 문체, 분명한 미술 용어 오인식만 바로잡고 추측 금지. 근거 없으면 빈 배열 → 화면 "언급되지 않음" |

## 4. 정책 확인 — **운영 전송 전 결정 필요**

| 항목 | 확인 내용 | 영향 |
| --- | --- | --- |
| 무료 등급 데이터 | Gemini API 약관: 무료(unpaid) 사용 시 입력·응답이 Google 제품 개선에 쓰이고 사람이 검토할 수 있음. 유료 등급은 쓰이지 않음. (EEA·영국·스위스 예외, 한국은 해당 없음) | **유료 등급(결제 연결) 키만** 사용 |
| **연령 조항** | Gemini API 추가 약관: 18세 이상만 API 사용, **18세 미만이 이용하거나 이용할 가능성이 높은 앱에서 사용 금지** | 입시 미술 학생(대부분 미성년자) 대상인 ART MATE는 **약관 위반 소지**. 법무 검토 또는 다른 제공 경로(예: Google Cloud Vertex AI의 별도 약관, 다른 LLM 제공자) 검토 필요 |
| 동의 | 기존 AI 전송 동의(FEEDBACK_SUMMARY, `granted_by` SELF/GUARDIAN) 재사용. 미동의 시 요청 409, 동의 철회 시 대기 작업 취소 | 14세 미만 보호자 동의 흐름 유지 |
| 전송 범위 | 대본의 구간 번호·시각·문장만 (이름·학원·작품 제목·사용자 ID 미전송). 녹음 안에서 말한 이름은 포함될 수 있음 → 동의서에 고지 | |

`AI_PROVIDER_TERMS_CONFIRMED=true`는 위 두 항목(유료 등급, 연령 조항 포함 약관 검토)이 끝난 뒤에만 설정한다.

## 5. 설정 방법 (이름과 위치만)

| 위치 | 이름 | 종류 | 값 |
| --- | --- | --- | --- |
| Render | `AI_SUMMARY_ENABLED` | 환경 변수 | `true` |
| Render | `AI_PROVIDER_TERMS_CONFIRMED` | 환경 변수 | `true` (§4 확인 후) |
| Render | `WORKER_DISPATCH_TOKEN` | 환경 변수(비밀) | fine-grained PAT (이 저장소, Actions 읽기·쓰기) — 없으면 요약이 수 시간 대기 |
| GitHub Actions | `AI_SUMMARY_ENABLED` | Variable | `true` |
| GitHub Actions | `AI_PROVIDER_TERMS_CONFIRMED` | Variable | `true` (§4 확인 후) |
| GitHub Actions | `GEMINI_API_KEY` | Secret | 결제가 연결된 Google Cloud 프로젝트의 Gemini API 키 |
| (선택) | `GEMINI_MODEL` | | 기본 `gemini-3.1-flash-lite` |

Render에는 `GEMINI_API_KEY`를 넣지 않는다 (호출은 Worker에서만). 프론트엔드(Vercel)는 변경 없음.

## 6. 비용·한도 (공개 자료 기준, 공식 가격표 확인 필요)

- Gemini 3.1 Flash-Lite: 입력 100만 토큰당 약 $0.25, 출력(사고 토큰 포함) 약 $1.50.
- 5분 첨삭 1건 추정: 입력 약 3,500토큰(규칙·스키마 포함) + 출력 약 800토큰 → **약 $0.002**. 월 1,000건 ≈ $2.
- 앱 자체 한도: 학생 1명 하루 20건(`AI_SUMMARY_DAILY_LIMIT`), 전사 3만 자 초과 시 요약 안 함, 출력 4,096토큰.
- Gemini 429(사용량 초과)는 재시도 가능 오류로 처리 → 지수 백오프 후 재시도, 최대 3회 후 실패 → 학생이 다시 시도.

## 7. 테스트

| 시나리오 | 결과 | 종류 |
| --- | --- | --- |
| 30초·1분·5분 대본 → 자동 요약 → 저장·복원(새로고침) | 통과 | **모의(가짜 Gemini)** DB 테스트 `test_ai_summary_scenarios.py` |
| 기존 대본 요약, 대본 수정 후 최신 대본 재분석, 같은 대본 중복 요청 409 | 통과 | 모의 |
| AI 실패 후 재시도 (대본 유지) | 통과 | 모의 (+ 기존 429·잘못된 JSON 재시도 테스트) |
| 다른 학생 요약·대본·재생성 접근 404 | 통과 | 모의 |
| 동의 없는 사용자: 요약 409, 작업 없음 | 통과 | 모의 (+ 기존 동의 철회 시 취소 테스트) |
| 배포 환경 운영자 확인 전 전송 차단, 상태 API 이유 | 통과 | 단위 `test_ai_terms_gate.py` |
| **실제 Gemini 호출** | **미실행** — 키 없음, 유료 API·약관 승인 전 | — |
| 실제 녹음 → STT → 요약 화면 흐름 (휴대폰 포함) | 미실행 (운영 설정 전) | — |

## 8. 요약 결과 예시 (테스트용 가짜 응답 — 실제 Gemini 결과 아님)

입력 대본 구간: `[0] 전체적으로 구도는 안정적으로 잘 잡았어.` `[1] 근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보여.` `[2] 어두운 면을 한 톤 더 눌러주고 반사광은 조금만 남겨.` `[3] 다음 작품에서는 처음부터 큰 덩어리 명암을 먼저 잡자.`

- 전체 요약: 구도는 안정적이나 오른쪽 사과의 명암이 약해 형태가 떠 보인다.
- 잘한 점: 구도를 안정적으로 잡았다. (근거 [0])
- 개선할 점: 오른쪽 사과의 명암이 약해 형태가 떠 보인다. (근거 [1])
- 수정 방법: 어두운 면을 한 톤 더 누르고 반사광은 조금만 남긴다. (근거 [2])
- 다음 연습 과제: 처음부터 큰 덩어리 명암을 먼저 잡는다. (근거 [3])

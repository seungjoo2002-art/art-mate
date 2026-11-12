# v0.9.6 미성년자 대상 서비스용 LLM 제공자 선정 — 조사·설계

> 작성: 2026-11-12 · 조사·설계만 (유료 API 호출·운영 설정 변경 없음)
> 전제: PR #51(AI 첨삭 요약 활성화 준비)은 아직 **열린 상태**. 아래 설계는 #51 위에 얹는다.
> 관련: [ai-feedback-summary-v0.9.5.md](ai-feedback-summary-v0.9.5.md)

## 0. 결론

**추천: OpenAI API (Responses API + Structured Outputs, 기본 모델 `gpt-6.1-terra`, 비용 대안 `gpt-6-luna`)**

- 비교한 세 방식 중 **약관상 미성년자 대상 서비스를 명시적으로 허용**(안전 조치 조건)하는 것은 OpenAI뿐이다.
  - Google은 Gemini API와 Vertex AI 모두 Google 모델을 18세 미만 대상 서비스에 쓰지 못한다.
  - EXAONE은 라이선스가 비상업(연구·교육)으로 제한된다.
- API 입력은 기본적으로 학습에 쓰이지 않는다.
- JSON 스키마 강제 출력이 있어 지금의 Gemini 요약 코드(프롬프트·검증·근거 대조·저장·화면·성장 분석)를 **그대로 두고 LLM 호출부 하나만 바꾸면 된다**.
- 조건:
  - 13~17세는 보호자 동의를 받아야 한다(OpenAI 약관 + 개인정보보호법상 국외 이전 동의).
  - **13세 미만이 쓸 수 있으면 사전에 Zero Data Retention(ZDR) 승인이 필요**하다. 중학생 학년이 있으므로 ZDR을 신청하거나, 승인 전까지 중학생은 AI 요약에서 제외한다.

## 1. 약관 비교 (공식 문서 기준)

| 항목 | Google Cloud Vertex AI | OpenAI API | 자체 호스팅 EXAONE 4.0 |
| --- | --- | --- | --- |
| **미성년자 대상 서비스** | **불가 (Gemini 사용 시)**. Service Specific Terms 20(d): "Generative AI Service를 18세 미만이 대상이거나 이용할 가능성이 높은 웹사이트·앱·온라인 서비스에서 사용하지 않는다". 공개 자료상 예외는 *Google 사전 학습 모델을 쓰지 않는 경우*뿐인데, Gemini는 "Google Pre-Trained Model"(Google이 학습했고 오픈 모델로 공개하지 않은 모델)에 해당한다 (2026-04-02 개정판 확인) | **가능 (조건부)**. 개발자 문서 *Under-18 guidance*: 안전하고 연령에 맞는 콘텐츠를 위한 합리적 조치, 연령 확인(필요 시), 안전 도구, 최신 주력 모델 사용. **13세 미만 개인정보는 ZDR을 먼저 적용하기 전에는 처리하지 말 것**. 비즈니스 약관상 미성년자는 보호자 동의 필요 (공식 페이지가 자동 조회를 막아 원문은 커뮤니티 인용으로만 확인 → 계약 전 원문 확인 필요) | 라이선스에 연령 조항 없음 |
| **라이선스·상업 이용** | 유료 클라우드 계약 | 유료 API 계약 | **EXAONE AI Model License 1.2-NC: 연구·교육 목적만**. 수익을 내는 제품·서비스·앱 배포와 외부 배포는 금지, 상업 이용은 LG와 별도 계약 필요 |
| **데이터 학습** | "Customer Data를 사전 허가 없이 AI 모델 학습·미세조정에 쓰지 않음" (SST 18) | API 입력·출력은 **기본적으로 학습에 쓰지 않음** (opt-in일 때만) | 자체 서버 → 외부 학습 없음 |
| **보관** | Cloud 데이터 처리 부속서(DPA) 적용 | 남용 감시 로그 **최대 30일**. ZDR·수정된 남용 감시는 OpenAI 사전 승인 필요 | 자체 관리 |
| **처리 위치** | 리전 선택 가능 (서울 리전 등) | 한국은 **저장만** 지원(`kr.api.openai.com`), 처리 지역 선택은 일본·인도·호주(ZDR 필요) → 사실상 미국 등 국외 처리 | 자체 서버 위치 |
| **ART MATE 적합성** | ✗ (Gemini 사용 시 약관 위반 소지) | ○ (보호자 동의·13세 미만 처리 조건) | ✗ (상업 서비스면 별도 라이선스, 학교 과제 수준 비영리라도 "외부 배포 금지" 해석 위험) |

## 2. 성능·비용 비교

**실측 없음** — 유료 API 호출 금지(이번 범위). EXAONE 1.2B는 이 PC에 내려받혀 있으나 메모리 부족(여유 약 1GB)으로 실행하지 않았다.

| 방식 | 한국어 요약 품질 (근거) | 구조화 JSON | 첨삭 1건 비용* | 월 1,000건 |
| --- | --- | --- | --- | --- |
| Vertex AI Gemini 3.1 Flash-Lite | 기존 프롬프트·스키마가 이 모델 기준으로 작성됨 | `responseJsonSchema` (현재 코드) | 약 $0.002 | 약 $2 |
| OpenAI `gpt-6-luna` | 공개 설명: "대량·집중 작업용 가장 효율적인 모델". 한국어 첨삭 품질 미측정 | Structured Outputs (strict) | 약 $0.00075 | 약 $0.75 |
| OpenAI `gpt-6.1-terra` | 공개 설명: "명확하고 자연스러운 글쓰기"에 적합한 빠른 모델. 미측정 | 〃 | 약 $0.0075 | 약 $7.5 |
| OpenAI `gpt-6.1-sol` | Astra에 가까운 성능 (공개 설명). 미측정 | 〃 | 약 $0.015 | 약 $15 |
| EXAONE 4.0 1.2B (CPU) | 한국어 특화 소형 모델. 근거 번호를 지키는 JSON 요약 품질은 불확실 | 오픈소스 제약 디코딩 필요 | 0 (Actions 러너) + 처리 수 분 | 0 |
| EXAONE 4.0 32B (GPU) | KMMLU-Redux 72.7 (모델 카드, 비추론 모드) | 〃 | GPU 서버 상시 운영 시 월 수백 달러 + 상업 라이선스 | — |

\* 가정: 5분 첨삭 1건 = 입력 약 3,500토큰(규칙·스키마 포함) + 출력 약 800토큰. 가격은 2026-11 공개 가격표 기준(100만 토큰당, 입력/출력): gpt-6-luna $0.10/$0.50, gpt-6.1-terra $1.00/$5.00, gpt-6.1-sol $2.00/$10.00, Gemini 3.1 Flash-Lite 약 $0.25/$1.50.

**모델 선택**: OpenAI 가이드는 미성년자 대상 서비스에 "최신 주력(flagship) 모델"을 권한다.
- 가격표의 "Flagship models" 구분에는 gpt-6 계열 전체(luna 포함)가 들어 있다.
- 모델 안내 페이지는 Astra만 "flagship"이라고 부른다.

해석이 갈리므로, 기본값은 최신 세대 중 글쓰기에 맞춘 `gpt-6.1-terra`로 하고, 계약 시 OpenAI에 확인한 뒤 `gpt-6-luna`로 낮출지 정한다.

**품질 평가 계획 (승인 후)**: 동의를 받은 실제 대본 5건 이상을 모델별로 같은 프롬프트에 넣고, 기존 서버 검증으로 자동 채점한다.
- JSON 통과율
- 버려진 항목 비율(`dropped_item_count`): 근거 번호가 없거나 근거 문장과 표현이 겹치지 않은 항목
- `insufficient_content` 오판
- 사람 평가: 잘한 점·개선점이 선생님 말과 맞는지

## 3. 기존 코드와의 호환성

현재 구조는 제공자에 독립적이다.

```text
JobRunner._call_llm(system, prompt, schema) → SummaryLlm.generate() → LlmResponse(text, tokens, finish_reason, model_name)
  → AiSummaryOutput(Pydantic) 검증 → 근거 번호·2-gram 대조 → feedback_summaries / feedback_items 저장 → 화면·성장 분석
```

| 항목 | Gemini(현재) | OpenAI로 바꿀 때 |
| --- | --- | --- |
| 호출 인터페이스 | `SummaryLlm` 프로토콜 | 같은 프로토콜의 새 구현 1개 |
| 시스템 지시 | `systemInstruction` | `instructions` |
| JSON 강제 | `responseJsonSchema` | `text.format = {type: "json_schema", strict: true, schema}`. strict 모드: 모든 객체 `additionalProperties: false`, 모든 속성 `required`(현재 스키마는 이미 모두 required), nullable은 `["string","null"]` (현재 category가 이미 이 형식). `maxItems` 등 일부 키워드 지원 여부는 확인 필요 → 지원하지 않으면 제거하고 기존 Pydantic `max_length` 검증에 맡김 |
| 오류 코드 | 429 → `LLM_RATE_LIMITED`, 401·403 → `LLM_AUTH_FAILED`, 5xx → `LLM_UNAVAILABLE`, 잘림 → `LLM_OUTPUT_TRUNCATED`, 차단 → `LLM_BLOCKED` | 같은 코드로 매핑 (`status: "incomplete"` → 잘림, refusal → 차단) → 재시도·화면 문구 변경 없음 |
| 토큰 사용량 | `usageMetadata` | `usage.input_tokens / output_tokens` → 기존 비용 집계 컬럼 그대로 |
| 프롬프트·검증·저장·화면·성장 분석 | — | **변경 없음** (`model_name`만 바뀌어 저장됨) |

## 4. 최소 수정 범위 (구현은 다음 단계, 승인 후)

| # | 파일 | 변경 |
| --- | --- | --- |
| 1 | `backend/app/integrations/ai/openai_llm.py` (신규) | Responses API 호출(`store: false`), `to_strict_schema()` 변환, 오류 코드 매핑 |
| 2 | `backend/app/core/config.py` | `AI_PROVIDER`(`gemini`\|`openai`, 기본 gemini), `OPENAI_API_KEY`, `OPENAI_MODEL`(기본 `gpt-6.1-terra`), `OPENAI_API_BASE`, 시간 제한. 키 존재 여부 판단을 제공자별로 |
| 3 | `backend/app/integrations/ai/gemini.py` `build_llm` | `AI_PROVIDER`에 따라 구현 선택 (#51의 `ai_summary_active` 차단 장치 그대로) |
| 4 | `backend/app/models/enums.py` + **Alembic 마이그레이션** | `AiProvider.OPENAI` 추가 → `ai_processing_consents.provider` CHECK 제약 확장 (varchar라 값 추가만, 데이터 변경 없음) |
| 5 | `backend/app/services/ai_feedback.py`·`ai_cleanup.py` | 동의 조회·저장의 제공자를 설정값으로 (현재 `GOOGLE_GEMINI` 고정) |
| 6 | `AI_CONSENT_VERSION` | `2026-12-ai-v2` 등으로 올림 → 학생 재동의 (기존 Gemini 동의로 OpenAI 전송 불가) |
| 7 | `frontend/.../AiConsentForm.jsx` | 제공받는 곳 "OpenAI, L.L.C. (미국)", 처리 국가·보관(남용 감시 최대 30일, 학습 미사용), **만 18세 미만은 보호자 동의**(현재 14세 미만만 보호자) |
| 8 | 연령 조건 | 학년 `MIDDLE_SCHOOL`은 13세 미만일 수 있음 → ZDR 승인 전에는 AI 요약 요청을 막는 서버 검사 1개 추가 (학년 외 나이 정보는 저장하지 않는 기존 원칙 유지) |
| 9 | `.github/workflows/stt-worker.yml` | `OPENAI_API_KEY` 시크릿, `AI_PROVIDER` 변수 전달 |
| 10 | 테스트 | `httpx.MockTransport`로 성공·429·401·incomplete·refusal·스키마 변환 단위 테스트. 기존 DB 시나리오는 가짜 LLM이라 그대로 통과 |

**변경하지 않는 것**: 요약 결과 구조(`AiSummaryOutput`), 프롬프트 규칙, 근거 대조, DB 테이블, 결과 화면, 성장 분석 연동, 작업 큐·재시도·중복 방지.

## 5. 실제 활성화 절차

1. **정책 확정 (운영자·법무)**
   - OpenAI Business Terms 원문의 미성년자·보호자 동의 조항
   - 개인정보보호법 국외 이전 고지(이전받는 자·국가·항목·목적·보관 기간)
   - 13세 미만 처리 방침(ZDR 신청 또는 중학생 제외)
2. **구현 PR** (§4) — DB 마이그레이션 포함이므로 별도 검토 후 병합.
3. **OpenAI 조직 준비**
   - 전용 Project와 API 키 생성
   - 월 사용 한도·예산 알림 설정
   - Data controls에서 학습 사용이 꺼져 있는지 확인
   - 필요 시 ZDR 신청
4. **품질 평가 (유료 호출 승인 후)**: 동의받은 실제 대본으로 `gpt-6.1-terra`와 `gpt-6-luna` 비교(§2) → 모델 확정.
5. **설정 (이름·위치만)**
   - GitHub Actions: Secret `OPENAI_API_KEY`, Variables `AI_PROVIDER=openai`, `AI_SUMMARY_ENABLED=true`, `AI_PROVIDER_TERMS_CONFIRMED=true`, `AI_CONSENT_VERSION`(새 버전)
   - Render: `AI_PROVIDER=openai`, `AI_SUMMARY_ENABLED=true`, `AI_PROVIDER_TERMS_CONFIRMED=true`, `AI_CONSENT_VERSION`(같은 값), `WORKER_DISPATCH_TOKEN`
   - Gemini 관련 값은 비우거나 삭제
6. **배포**: 백엔드(마이그레이션 → API) → Worker 설정 → 프론트(동의서) 순. 학생 재동의 후 요약 시작. 첫 주는 실패 코드·토큰 사용량·`dropped_item_count`를 모니터링.

## 6. 참고 (공식 문서)

- Google Cloud Service Specific Terms (Generative AI Services 20(d), Training Restriction 18, Google Pre-Trained Model 정의): https://cloud.google.com/terms/service-terms
- Gemini API Additional Terms: https://ai.google.dev/gemini-api/terms
- OpenAI Under-18 API guidance: https://developers.openai.com/api/docs/guides/safety-checks/under-18-api-guidance
- OpenAI Data controls (학습·보관·ZDR·데이터 처리 위치): https://developers.openai.com/api/docs/guides/your-data
- OpenAI Pricing / Models / Structured Outputs: https://developers.openai.com/api/docs/pricing , https://developers.openai.com/api/docs/models , https://developers.openai.com/api/docs/guides/structured-outputs
- EXAONE 4.0 License (1.2-NC): https://huggingface.co/LGAI-EXAONE/EXAONE-4.0-32B/blob/main/LICENSE

조사 범위 밖: 그 밖의 LLM 제공자는 이번 비교에 넣지 않았다.

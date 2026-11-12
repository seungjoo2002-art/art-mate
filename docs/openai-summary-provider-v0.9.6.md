# v0.9.6 OpenAI 요약 제공자 + 연령 확인·보호자 동의 — 구현·활성화
> **2026-11-13 갱신**: 연령 구간은 만 14세 기준(UNDER_14 / TEEN / ADULT, 마이그레이션 0013)으로 바뀌었다 → [minors-ai-policy-v0.9.6.md](minors-ai-policy-v0.9.6.md)

> 작성: 2026-11-12 · 브랜치 `feature/openai-summary-provider` (PR #51 브랜치 위)
> 설계: [llm-provider-selection-v0.9.6.md](llm-provider-selection-v0.9.6.md) · 이전: [ai-feedback-summary-v0.9.5.md](ai-feedback-summary-v0.9.5.md)
> **실제 OpenAI 호출 없음** (모의 테스트만). 운영 DB 마이그레이션·운영 설정 변경 없음.

## 1. 공식 문서 재확인 (2026-11-12)

| 항목 | 확인 내용 | 출처 |
| --- | --- | --- |
| 모델 ID | `gpt-6.1-terra`, `gpt-6-luna` — 둘 다 Responses API·Chat Completions·Batch, **Structured Outputs 지원**, 추론 강도 none~max(기본 medium) | developers.openai.com 모델 페이지 |
| 가격 (100만 토큰, Standard) | terra: 입력 $1 / 캐시 입력 $0.05 / 출력 $5 · luna: 입력 $0.10 / 캐시 $0.01 / 출력 $0.50. 추론 토큰은 출력으로 과금. 27만 2천 토큰 초과 입력은 할증 | 모델·가격 페이지 |
| Structured Outputs | `text.format = {type: "json_schema", name, schema, strict: true}`. 모든 속성 required + 모든 객체 `additionalProperties: false`, nullable은 `["string","null"]`, `maxItems`·enum 지원, 거절은 `refusal` 항목 | Structured Outputs 가이드 |
| 응답 | `status`(completed/incomplete/failed …), `usage.input_tokens/output_tokens/output_tokens_details.reasoning_tokens`. **`output_text`는 SDK 전용** → `output[].content[]`에서 직접 읽음 | API 레퍼런스 |
| 학습 | API 입력·출력은 기본적으로 학습에 쓰지 않음 (opt-in일 때만) | Data controls |
| 보관 | 남용 감시 로그 최대 30일. ZDR·수정된 남용 감시는 **OpenAI 사전 승인** 필요 | Data controls |
| 처리 위치 | 한국은 저장만(`kr.api.openai.com`), 처리 지역 지정 불가 → 국외 처리 | Data controls |
| 미성년자 | 연령에 맞는 안전 조치, 필요 시 연령 확인, 최신 모델 사용. **만 13세 미만 개인정보는 ZDR 적용 전 처리 금지** | Under-18 API guidance |
| 보호자 동의 | 만 18세 미만 보호자 허락 (OpenAI 약관) — **비즈니스 약관 원문은 자동 조회가 차단되어 직접 확인하지 못함** → 운영자 확인 항목 | (미확인) |
| 국내법 | 만 14세 미만은 법정대리인 동의 + 확인(개인정보 보호법 제22조의2), 확인을 위해 법정대리인 성명·연락처 수집 가능(시행령 제17조의2). 국외 이전 고지 조문(제28조의8)은 원문 확인 필요 | 법령 해설 자료 |

## 2. 구현

### 2.1 제공자 교체 구조 (요약 결과·검증·성장 분석 변경 없음)

```text
build_llm(settings)  →  AI_PROVIDER=openai: OpenAiClient  |  gemini: GeminiClient   (같은 SummaryLlm, 같은 오류 코드)
  OpenAiClient: POST /v1/responses {model, instructions, input, text.format(json_schema strict),
                reasoning.effort=low, max_output_tokens, store=false}
  → 기존 AiSummaryOutput 검증 → 근거 번호·문장 대조 → feedback_summaries/items → 화면·성장 분석 (그대로)
```

- 스키마: `to_strict_schema()`가 기존 요약·성장 분석 스키마에 `additionalProperties: false`만 더한다 (원본은 Gemini 경로용으로 그대로). required가 빠진 스키마는 오류로 막는다.
- 모델: 설정값을 `gpt-6.1-terra`(기본) / `gpt-6-luna`(저비용)로 **제한** — 확인되지 않은 모델명은 설정 단계에서 거부.
- 오류 매핑: 429 → `LLM_RATE_LIMITED`(재시도) · 5xx·타임아웃 → 재시도 · 401/403 → `LLM_AUTH_FAILED` · `incomplete`(max_output_tokens) → `LLM_OUTPUT_TRUNCATED` · 콘텐츠 필터·거절 → `LLM_BLOCKED`. 기존 재시도·화면 문구 그대로.
- 중복 방지·하루 한도·근거 대조·대본 수정 후 재분석은 기존 코드 그대로.

### 2.2 연령 확인·보호자 동의 (학년으로 판단하지 않음)

| 단계 | 내용 |
| --- | --- |
| 학생 동의 | 동의서 v2(`2026-12-ai-v2`, 성장 `2026-12-growth-v2`)에 **생년월 입력**. 서버가 나이 구간(UNDER_13 / MINOR / ADULT)만 저장, 생년월은 저장하지 않음. 생일을 그 달 말일로 보아 **나이를 적게(보수적으로)** 계산 |
| 성인 | 본인 동의로 바로 유효 |
| 만 13~17세 | 동의가 "보호자 확인 대기"로 저장되고 **보호자 확인 링크**(7일, 1회용, 토큰은 해시만 저장)를 발급 → 학생이 복사·공유 → 보호자가 로그인 없이 `/guardian-consent/{token}`에서 동의 내용 확인, 성명·관계 입력, 동의 → 유효 |
| 만 13세 미만 | 보호자 확인을 받아도 **운영자 ZDR 승인(`AI_ZDR_APPROVED`) 전에는 전송 차단** |
| 판정 위치 | API(요청 시)와 Worker(보내기 직전) 모두 `ai_consent_policy.evaluate` — 큐에 들어간 뒤 조건이 바뀌면 Worker가 취소 |
| 제공자 변경 | 동의는 제공자별. Gemini 동의로는 OpenAI 전송 불가 (재동의) |

**한계 (운영자 판단 필요)**: 보호자 확인은 "학생이 보낸 링크를 보호자가 열어 성명·관계를 입력"하는 방식이다. 학생이 직접 누르는 것을 기술적으로 막지는 못한다. 개인정보 보호법 시행령의 법정대리인 동의 확인 방법(문자·전자우편·본인확인 등)에 맞는지 법률 검토가 필요하다. 필요하면 보호자 휴대폰 본인확인이나 전자우편 회신 방식으로 강화한다(유료 본인확인 서비스 필요할 수 있음).

### 2.3 DB 마이그레이션 `0012` (운영 미적용)

`ai_processing_consents`:
- provider CHECK에 `OPENAI` 추가
- 새 NULL 허용 컬럼: `age_band`, `guardian_name`, `guardian_relationship`, `guardian_confirmed_at`, `guardian_token_hash`(UNIQUE), `guardian_token_expires_at`
- CHECK: 확인됐으면 성명·관계 필수

기존 행은 그대로 두며 데이터 이관은 없다. downgrade는 OpenAI 동의 행을 삭제하므로 주의.
**PR #48의 `0011`(main 미반영)과 같은 부모(0010)** → 둘 중 나중에 main에 들어가는 쪽의 `down_revision`을 조정해야 한다.

### 2.4 API (추가·변경)

| API | 내용 |
| --- | --- |
| `POST /ai-processing-consents` | `birth_year_month` 필수(`AI_AGE_REQUIRED`). 응답에 `reason`, 미성년자면 `guardian_token`(한 번만). `granted_by` 입력은 무시 |
| `GET /ai-processing-consents/me` | `provider`, `reason`(NOT_CONSENTED / GUARDIAN_PENDING / UNDER_13_BLOCKED), `consent.age_band`·`guardian_confirmed_at` |
| `POST /ai-processing-consents/me/guardian-link` | 보호자 링크 재발급 (이전 링크 무효) |
| `GET/POST /guardian-consents/{token}` | 로그인 없이 보호자 확인 (학생 이름·작품·전사 내용 미노출, 1회용, 만료 404 `GUARDIAN_LINK_INVALID`) |
| `GET /meta/ai-features` | `ai_provider` 추가 |

## 3. 환경 변수 (이름·위치만)

| 위치 | 이름 | 값 |
| --- | --- | --- |
| **GitHub Actions Secret** | `OPENAI_API_KEY` | OpenAI 프로젝트 키 (**여기에만** — Render·Vercel·코드에 넣지 않음) |
| GitHub Actions Variable | `AI_PROVIDER` | `openai` (비우면 openai) |
| GitHub Actions Variable | `OPENAI_MODEL` | 비우면 `gpt-6.1-terra`, 저비용은 `gpt-6-luna` |
| GitHub Actions Variable | `AI_SUMMARY_ENABLED`, `AI_PROVIDER_TERMS_CONFIRMED` | `true` (운영자 검토 후) |
| GitHub Actions Variable | `AI_CONSENT_VERSION`, `AI_GROWTH_CONSENT_VERSION` | 비우면 앱 기본값 `2026-12-ai-v2` / `2026-12-growth-v2` (Render와 같아야 함) |
| GitHub Actions Variable | `AI_ZDR_APPROVED` | ZDR 승인 후에만 `true` |
| Render | `AI_PROVIDER=openai`, `AI_SUMMARY_ENABLED`, `AI_PROVIDER_TERMS_CONFIRMED`, 같은 동의서 버전, `AI_ZDR_APPROVED`, `WORKER_DISPATCH_TOKEN` | 키는 넣지 않음 |
| Vercel | 없음 | — |

## 4. 예상 비용 (공식 가격 기준 추정)

가정: 5분 첨삭 1건 = 입력 약 3,500토큰(규칙·스키마 포함) + 출력 약 1,100토큰(요약 약 800 + 추론 low 약 300 — 미측정).

| 모델 | 1건 | 월 1,000건 | 월 5,000건 |
| --- | --- | --- | --- |
| `gpt-6.1-terra` (기본) | 약 $0.009 | 약 $9 | 약 $45 |
| `gpt-6-luna` (저비용) | 약 $0.0009 | 약 $0.9 | 약 $4.5 |

성장 분석 AI(GROWTH_AI_ENABLED)는 별도. OpenAI 조직에서 월 예산 한도를 설정해 초과를 막는다.

## 5. 테스트 (모두 모의 — 실제 API 호출 없음)

| 대상 | 내용 |
| --- | --- |
| `test_openai_llm.py` | 요청 형식(모델·instructions·strict 스키마·store=false·reasoning·Bearer), 응답 파싱(추론 항목 건너뜀·토큰), 429/500/401/400, incomplete·거절·빈 응답, 네트워크 오류, 제공자 선택, 확인 안 된 모델명 거부, 성장 분석 스키마 변환 |
| `test_ai_consent_policy.py` | 연령 구간 경계(보수적 계산), 잘못된 생년월, 판정 규칙(버전·제공자·연령 없음·보호자 대기·13세 미만·ZDR), 토큰 해시·만료 |
| `tests/db/test_ai_guardian_consent.py` | 미성년자 동의 → 보호자 링크(로그인 없음, 학생 정보 미노출, 1회용) → 요약 가능 / 확인 전 요약 409 / 13세 미만 ZDR 전 차단, 큐 대기 중 승인 해제 시 Worker 취소(전송 없음) / 성인 / 제공자 변경 시 재동의 / 링크 재발급·만료 |
| 기존 DB 테스트 | 동의 요청에 생년월(성인) 추가, 버전 v2. 요약·근거·성장 분석·중복 방지 테스트 그대로 |
| 프론트 | `consentCopy.test.js` (제공자·국외·보관·연령 문구, 사유 문구, 링크) |

## 6. 실제 활성화 절차

1. **운영자·법무 확인**:
   - OpenAI 비즈니스 약관 원문(미성년자·보호자 동의)
   - 보호자 확인 방식의 법적 적정성(§2.2 한계)
   - 국외 이전 고지 문구
   - 동의서 최종 문구(`frontend/src/features/feedback/consentCopy.js`)
2. **OpenAI 조직**:
   - 전용 프로젝트와 키 발급
   - 월 예산 한도·알림 설정
   - Data controls에서 학습 사용이 꺼져 있는지 확인
   - 만 13세 미만 학생을 받으려면 ZDR 신청
3. **PR 병합 순서**: #51 → 이 PR (DB 마이그레이션 포함, #48의 0011과 순서 조정).
4. **운영 DB 마이그레이션** `alembic upgrade head` — 운영자가 백업 후 직접 실행.
5. **(유료 호출 승인 후) 품질 확인**:
   - 동의를 받은 실제 대본 5건 이상으로 terra·luna 비교: JSON 통과율, `dropped_item_count`, 사람 평가
   - 모델 확정 → `OPENAI_MODEL`
6. **설정** (§3) → 백엔드 배포 → 프론트 배포 → 학생 재동의(보호자 확인 포함) → 첫 주 실패 코드·토큰 사용량 모니터링.

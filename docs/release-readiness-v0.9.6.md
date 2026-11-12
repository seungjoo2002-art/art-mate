# v0.9.6 운영 배포 준비 — 브랜치·마이그레이션·보안·설정 점검
> **2026-11-13 갱신**: `AI_MINORS_ENABLED`는 연령별 설정(`AI_TEENS_ENABLED`·`AI_TEEN_GUARDIAN_REQUIRED`·`AI_UNDER14_ENABLED`)으로 바뀌었다 → [minors-ai-policy-v0.9.6.md](minors-ai-policy-v0.9.6.md)

> 작성: 2026-11-12. 이번 작업에서 하지 않은 것: 운영 DB 변경, 실제 OpenAI 호출, 결제, main 병합.

## 1. 브랜치·PR 관계 (확인 결과)

| PR | 상태 | 문제 |
| --- | --- | --- |
| #47 | main에 병합 (11-11 06:24) | — |
| #48 | `feature/ver2-p0-community-exam`에 병합 (06:25, #47 병합 **12초 뒤**) | **main에 없음** (마이그레이션 0011 포함) |
| #51 | main에 병합 (11-12 11:52:21) | — |
| #52 | `feature/ai-feedback-summary-activation`에 병합 (11:52:44, #51 병합 **23초 뒤**) | **main에 없음** (OpenAI·마이그레이션 0012 포함) |

원인: 연결 PR(기준 브랜치가 다른 PR 브랜치)을 기준 PR이 병합된 뒤에 병합해서, 변경이 이미 끝난 브랜치에만 들어갔다.

**해결**: main을 대상으로 새 PR 2개를 만든다.
- PR A (`release/ver2-p1-into-main`): #48 내용
- PR B (`release/openai-summary-into-main`): A + #52 내용 + 마이그레이션 계보 정리

**앞으로는 연결 PR을 쓰지 않고, 모든 PR을 main 대상으로 만든다.**

## 2. 마이그레이션 계보 정리

```text
수정 전: 0010 ─┬─ 0011 (#48 브랜치)        ← head 2개 (alembic upgrade head 실패)
              └─ 0012 (#52 브랜치)
수정 후: 0009 → 0010 → 0011 → 0012 (head 1개)
```

- 0012의 `down_revision`을 `"0011"`로 바꿨다. 0011(`profiles`·`community_comments` 컬럼 추가)과 0012(`ai_processing_consents`)는 서로 다른 테이블만 바꾼다.
- 두 마이그레이션 모두 **추가만** 한다: 컬럼·CHECK·UNIQUE 추가, 데이터 변경 없음, 한 트랜잭션.
- `community_comments.is_anonymous`는 `DEFAULT false NOT NULL`이다. PostgreSQL 11 이상은 테이블을 다시 쓰지 않는다.
- 운영에 적용될 SQL 미리보기 (DB 연결 없이): `cd backend && uv run alembic upgrade 0010:head --sql`

### 2.1 운영 DB가 어디까지 적용됐는지 확인하는 방법 (운영자가 읽기만)

Supabase → SQL Editor (읽기 전용 쿼리만):

```sql
SELECT version_num FROM alembic_version;                       -- 현재 버전
SELECT column_name FROM information_schema.columns              -- 0011 적용 흔적
 WHERE table_name = 'profiles' AND column_name IN ('real_name', 'exam_stage_targets');
SELECT column_name FROM information_schema.columns              -- 0012 적용 흔적
 WHERE table_name = 'ai_processing_consents' AND column_name IN ('age_band', 'guardian_token_hash');
```

| `version_num` | 0011 컬럼 | 0012 컬럼 | 의미 | 할 일 |
| --- | --- | --- | --- | --- |
| `0009` 또는 `0010` | 없음 | 없음 | 정상 (main 기준) | 백업 → `alembic upgrade head` (0010 → 0011 → 0012) |
| `0011` | 있음 | 없음 | #48 브랜치에서 누군가 적용 | 백업 → `alembic upgrade head` (0012만) |
| `0012` | 있음 | 있음 | 이미 최신 | 없음 |
| **`0012`** | **없음** | 있음 | 이전 #52 브랜치(0012가 0010 바로 다음)로 적용됨 | **upgrade 하지 말 것**. 0011 컬럼 3개를 수동 추가해야 한다 (§2.2) |

### 2.2 예외 처리 (마지막 경우만, 운영자 판단)

```sql
-- 0011과 같은 결과 (이미 있으면 건너뜀). 실행 전 백업
ALTER TABLE community_comments ADD COLUMN IF NOT EXISTS is_anonymous BOOLEAN DEFAULT false NOT NULL;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS real_name VARCHAR(50);
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS exam_stage_targets JSONB;
```

그다음 `alembic check`(로컬에서 운영 DB 대상)로 차이가 없는지 확인한다.

## 3. 검증 결과

| 항목 | 방법 | 결과 |
| --- | --- | --- |
| 새 DB | 테스트 DB에서 `base → head`. CI는 `upgrade head → downgrade base → upgrade head → alembic check` | CI (PR B) |
| 기존 DB | `test_migrations_v096.py`: 0010으로 내린 DB에 학생·Gemini v1 동의 저장 → 0011 → 0012 단계별 업그레이드 → 기존 행 보존, 새 컬럼 NULL, 제약, 0011로 되돌림(OpenAI 행만 삭제) → 다시 head → `alembic check` | CI (PR B) |
| Gemini·OpenAI 동의 분리 | 같은 학생·목적이어도 제공자별 행. 유효 동의 1개 제약은 제공자별. 이전 Gemini 동의로는 OpenAI 전송 불가, 철회도 현재 제공자 행만 (`test_worker_openai_pipeline.py`, 마이그레이션 테스트) | CI |
| Worker STT → AI 요약 | `test_worker_openai_pipeline.py`: `run_batch`(`--once`와 같은 경로)에서 서버 STT 완료 → 요약 작업 자동 생성 → 실제 `OpenAiClient`가 모의 HTTP로 Responses API 요청(모델·strict·store=false 확인) → 요약·근거 저장·토큰 기록·`model_name` | CI |
| 미성년자 차단 | 기본 `AI_MINORS_ENABLED=false`: 보호자가 확인해도 `MINOR_BLOCKED`, Worker도 전송 안 함 (대본은 정상) | 단위 + DB 테스트 |
| 모델 ID | 공식 모델 목록에 `gpt-6.1-terra`·`gpt-6-luna` 있음, 지원 중단 목록에 없음 (`gpt-6-luna`는 GPT-4o mini의 권장 대체 모델) | 2026-11-12 확인 |
| Structured Outputs 스키마 | 요약·성장 설명·추천 스키마 3개: 공식 지원 키워드만 사용, 모든 객체 `additionalProperties: false`, 모든 속성 required, 최상위 object, 중첩 2단계, 속성 최대 19개, enum 값 최대 59개 (한도 10단계·5,000개·1,000개) | 단위 테스트로 고정 |

## 4. 보호자 확인 링크 — 보안상 한계와 법률 검토 항목

### 4.1 기술적으로 막은 것

- 토큰: 256비트 무작위, DB에는 SHA-256만 저장. 7일 만료, 확인하면 즉시 무효. 재발급하면 이전 링크 무효.
- 보호자 화면: 학생 이름·작품·전사 내용을 보여 주지 않는다 (제공자·목적·버전·연령 구간만).
- 판정은 API와 Worker(보내기 직전) 두 곳에서 한다. 큐에 들어간 뒤 조건이 바뀌면 취소한다.

### 4.2 한계 (해결되지 않음)

| 한계 | 영향 | 보완안 |
| --- | --- | --- |
| **보호자 본인 확인 없음** | 링크를 가진 사람이면 누구나 "보호자"로 동의할 수 있다. 학생이 직접 열어 아무 이름이나 입력해도 막지 못한다 | 휴대폰 본인확인(유료 본인확인 서비스), 보호자 전자우편 회신, 문자 인증 |
| **나이를 스스로 입력** | 학생이 생년월을 속여 성인으로 동의할 수 있다 | 가입 시 연령 확인, 학원·학교 확인, 본인확인 |
| 토큰이 URL 경로에 있음 | 브라우저 기록, 메신저 미리보기, 서버·CDN 접근 로그(Render·Vercel)에 남을 수 있다. 1회용·만료로 피해 범위는 제한 | URL 조각(#)으로 옮기고 POST 본문으로만 서버에 전달 |
| 요청 횟수 제한 없음 | 토큰 추측은 사실상 불가능(256비트)하지만 대량 요청을 막지 않는다 | API 앞단 요청 제한 |
| 보호자 연락처 미보관 | 보호자에게 철회·변경을 알릴 수 없다. 철회는 학생 계정에서만 가능 | 연락처를 받으면 보관·파기 정책 필요 |

### 4.3 법률 검토가 필요한 항목

1. **OpenAI 비즈니스 약관 원문**의 미성년자·보호자 조항. 공식 사이트가 자동 조회를 막아 원문을 확인하지 못했다.
2. **법정대리인 동의 확인 방법의 적정성** (개인정보 보호법 제22조의2, 시행령 제17조의2): 현재 링크 + 성명 입력 방식이 법정 확인 방법에 해당하는지. 특히 만 13세(만 14세 미만).
3. **스스로 입력한 나이를 근거로 성인을 판정해도 되는지**.
4. **국외 이전 고지·동의** (제28조의8): 이전받는 자·국가·시기와 방법·항목·목적·보유 기간·거부 방법. 동의서 문구는 `frontend/src/features/feedback/consentCopy.js`(법률 검토 전 초안).
5. 보호자 성명 보관 기간과 개인정보처리방침 반영.
6. 기존 Gemini 동의 기록의 보관·파기. 지금은 이력으로 남고 전송에는 쓰이지 않는다.

**결론: 4.3의 1·2·3이 해결될 때까지 미성년자 전송은 차단한다** (`AI_MINORS_ENABLED=false`, 기본값).

## 5. 환경 변수 체크리스트 (이름·위치만)

### 5.1 GitHub Actions (Settings → Secrets and variables → Actions)

| 종류 | 이름 | 값 | 상태 확인 |
| --- | --- | --- | --- |
| Secret | `WORKER_DATABASE_URL` | Supabase Session pooler | ✅ 있음 (2026-11-10) |
| Secret | `OPENAI_API_KEY` | OpenAI 프로젝트 키 (**여기에만**) | ☐ 없음 |
| Variable | `AI_PROVIDER` | `openai` (비우면 openai) | ☐ |
| Variable | `OPENAI_MODEL` | 비우면 `gpt-6.1-terra` / 저비용 `gpt-6-luna` | ☐ |
| Variable | `AI_SUMMARY_ENABLED` | `true` (활성화 시점) | ☐ 없음 |
| Variable | `AI_PROVIDER_TERMS_CONFIRMED` | `true` (§6 조건 충족 후) | ☐ 없음 |
| Variable | `AI_MINORS_ENABLED` | **`false` 유지** (법률 검토 후에만 true) | ☐ |
| Variable | `AI_ZDR_APPROVED` | `false` (OpenAI ZDR 승인 후에만 true) | ☐ |
| Variable | `AI_CONSENT_VERSION`, `AI_GROWTH_CONSENT_VERSION` | 비우면 앱 기본값 `2026-12-ai-v2` / `2026-12-growth-v2` | ☐ |
| Variable | `GROWTH_AI_ENABLED` | 선택 | ☐ |

### 5.2 Render (API 서버) — 키는 넣지 않는다

| 이름 | 값 |
| --- | --- |
| `STT_ENABLED` | `true` |
| `STT_SOURCE_URL_SECONDS` | `86400` |
| `WORKER_DISPATCH_TOKEN` | fine-grained PAT (이 저장소, Actions 읽기·쓰기) — 없으면 Worker가 몇 시간 지연 |
| `AI_PROVIDER` | `openai` |
| `AI_SUMMARY_ENABLED`, `AI_PROVIDER_TERMS_CONFIRMED`, `AI_MINORS_ENABLED`, `AI_ZDR_APPROVED`, 동의서 버전 | **GitHub Actions와 같은 값** |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | **넣지 않음** |

### 5.3 Vercel

변경 없음.

## 6. 실제 OpenAI 호출을 시작해도 되는 조건 (모두 충족)

1. PR A·B가 main에 병합되고 백엔드·Worker가 main으로 배포됨.
2. 운영 DB가 `0012`이고 §2.1 확인 쿼리 결과가 정상.
3. OpenAI 조직:
   - 전용 프로젝트·키 발급, 월 예산 한도·알림 설정
   - Data controls에서 학습 사용 꺼짐 확인
4. OpenAI 비즈니스 약관 원문 검토 완료 (§4.3-1).
5. 동의서 최종 문구 확정 (국외 이전 고지 포함, §4.3-4)과 개인정보처리방침 반영.
6. 성인 학생 대상으로만 시작: `AI_MINORS_ENABLED=false` 유지.
7. 유료 호출 승인 → 동의를 받은 성인 대본으로 소량 품질 확인 → 모델 확정.
8. 운영자가 `AI_PROVIDER_TERMS_CONFIRMED=true`를 Render·Actions에 설정.

미성년자 전송(`AI_MINORS_ENABLED=true`)은 §4.3의 1·2·3 해결과 보호자 확인 강화(§4.2) 뒤에만 켠다. 만 13세 미만은 그에 더해 OpenAI ZDR 승인이 필요하다.

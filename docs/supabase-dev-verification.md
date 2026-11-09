# Supabase 개발 DB · Storage 적용 검증 절차

> 작성: 2026-11-09 (v0.5.1) · 대상: 백엔드 A (검증), 프론트엔드 B (적용 담당)
> 역할 분담: **적용은 프론트엔드 담당자**(Alembic 0002~0004, `artworks`·`feedback-audio` 비공개 버킷, Storage RLS 정책). **백엔드 담당자는 같은 작업을 다시 실행하지 않고 결과만 확인**합니다.
> 운영 DB에는 이 절차를 실행하지 않습니다. v0.5.1 리비전 `0005`는 승인 전까지 개발 DB에 적용하지 않습니다.

## 1. 자동 점검 (읽기 전용 스크립트)

```bash
cd backend
uv run python -m scripts.verify_dev_environment          # backend/.env 의 DATABASE_URL 사용
uv run python -m scripts.verify_dev_environment --json
```

- 모든 쿼리를 `BEGIN READ ONLY` 트랜잭션에서 SELECT만 실행하고 마지막에 ROLLBACK 합니다. DDL·DML 없음.
- 접속 URL·호스트·키 값은 출력하지 않습니다 (설정됨/비어 있음만).
- 종료 코드: 0 통과, 1 실패 항목 있음, 2 DB 미설정·접속 실패.

| 점검 항목 | 기준 |
| --- | --- |
| `alembic.current` | `0004` (프론트 적용 목표) 또는 승인 후 `0005` |
| `tables.required` | 유지 기능 15개 테이블 존재 |
| `tables.rls_enabled` | 위 테이블 모두 RLS 활성화 (정책 없음 = PostgREST 직접 접근 차단) |
| `functions.artmate_private` | `can_access_artwork_object`, `manages_student`, `can_access_recording_object`: SECURITY DEFINER, PUBLIC 실행 권한 없음 |
| `storage.buckets` | `artworks`, `feedback-audio` 존재, `public = false` |
| `storage.policies` | `artmate_artworks_{select,insert,delete}`, `artmate_audio_{select,insert,delete}` 6개 |
| `storage.authenticated_execute` | `authenticated` 역할에 권한 함수 EXECUTE |
| `env.SUPABASE_URL`, `env.SUPABASE_ANON_KEY` | 백엔드 `.env`에 값이 있음 |
| 제외 기능 테이블 행 수 | 출력만 (물리 삭제 계획용) |

### 2026-11-09 실행 결과 (백엔드 `.env`의 개발 DB)

| 항목 | 결과 |
| --- | --- |
| Alembic 현재 리비전 | **0004** ✅ |
| 필수 테이블 / RLS | ✅ / ✅ |
| 권한 함수 3개 | ✅ |
| 버킷 `artworks`, `feedback-audio` (비공개) | ✅ |
| Storage 정책 6개, authenticated EXECUTE | ✅ |
| `SUPABASE_URL` | ✅ 설정됨 |
| `SUPABASE_ANON_KEY` | ❌ **비어 있음** |
| 제외 기능 테이블 10개 | 모두 0행 |

## 2. `SUPABASE_ANON_KEY` 설정 (필수 조치)

백엔드는 service_role 키 없이 **사용자 access token + 공개 anon(publishable) 키**로 Storage API를 호출합니다 (`app/integrations/supabase/storage.py`). 이 값이 비어 있으면 Storage 클라이언트가 만들어지지 않아 다음 API가 **503 `STORAGE_NOT_CONFIGURED`** 입니다.

- `POST /artworks/{id}/photos`, `…/complete`, `…/url`, `include_urls=true`
- `POST /artworks/{id}/recordings`, `…/complete`, `…/url`, `include_urls=true`

조치:
1. Supabase Dashboard > Project Settings > API Keys에서 **anon(또는 publishable) 키**를 복사합니다. **service_role / secret 키는 사용하지 않습니다.**
2. `backend/.env`의 `SUPABASE_ANON_KEY=`에 붙여 넣습니다 (프론트 `VITE_SUPABASE_ANON_KEY`와 같은 값). 커밋하지 않습니다 (`.env`는 gitignore).
3. 배포 환경(Render)에도 같은 환경변수를 설정합니다.
4. 서버를 재시작하고 1절 스크립트를 다시 실행해 `env.SUPABASE_ANON_KEY`가 PASS인지 확인합니다.

## 3. 수동 확인 (사용자 토큰 필요)

실제 업로드·Signed URL·권한 격리는 Supabase 사용자 토큰이 있어야 하므로 개발 서버 + Swagger(또는 프론트 화면)로 확인합니다. 테스트 계정을 쓰고, 끝나면 만든 작품을 삭제합니다.

준비: 개발 서버 `uv run uvicorn app.main:app --reload`, 테스트 계정 4개
- 학생 S1, 학생 S2 (같은 학원 A, S1만 반 X 배정), 강사 T1 (반 X 담당), 강사 T2 (학원 A, 담당 반 없음)
- 토큰: 프론트에서 로그인 후 브라우저 콘솔 `(await supabase.auth.getSession()).data.session.access_token`

| # | 확인 | 방법 | 기대 결과 |
| --- | --- | --- | --- |
| 1 | 사진 업로드 | S1: `POST /artworks` (academy_id=A) → `POST /artworks/{id}/photos` → `uploadToSignedUrl` → `POST …/complete` (프론트 작품 상세 화면으로 해도 됨) | complete 200, `status: ACTIVE`, Storage `artworks/<S1>/<artwork>/<photo>.jpg` 존재 |
| 2 | 녹음 업로드 | S1: `POST /recording-consents` → 녹음 화면에서 녹음 저장 | complete 200, `feedback-audio` 버킷에 파일 존재, 목록 `recording_count: 1` |
| 3 | Signed URL | S1: `GET /artworks/{id}?include_urls=true`, `GET …/recordings/{rid}/url` | `url`이 열리고 이미지·오디오 재생, `url_expires_at` 이후 만료 |
| 4 | 학생 격리 | S2 토큰으로 S1 작품 `GET /artworks/{id}`, `…/photos/{pid}/url`, `…/recordings` | 404 |
| 5 | 학생 Storage 직접 접근 차단 | S2 토큰으로 `supabase.storage.from('artworks').createSignedUrl('<S1 경로>', 60)` | 오류 (RLS 거부) |
| 6 | 담당 강사 접근 | T1: `GET /academies/A/artworks`, `…/{id}?include_urls=true`, `…/recordings/{rid}/url` | 200, URL 재생 가능 |
| 7 | 비담당 강사 차단 | T2: `GET /academies/A/artworks/{id}` | 403, 목록에 S1 작품 없음 |
| 8 | 개인 작품 비공개 | S1이 academy_id 없이 만든 작품을 T1이 `GET /academies/A/artworks/{id}` | 404 |
| 9 | 공개 URL 차단 | `https://<ref>.supabase.co/storage/v1/object/public/artworks/<경로>` | 400/404 (비공개 버킷) |

SQL로 직접 확인하고 싶다면 (Supabase SQL Editor, 읽기만):

```sql
SELECT version_num FROM alembic_version;                                        -- 0004
SELECT id, public, file_size_limit FROM storage.buckets
 WHERE id IN ('artworks', 'feedback-audio');                                    -- public = false
SELECT policyname, cmd FROM pg_policies
 WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname LIKE 'artmate_%';  -- 6행
SELECT relname, relrowsecurity FROM pg_class
 WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1;      -- 모두 true
```

## 4. 0005 적용 (승인 후)

1. 이 PR이 develop에 병합되고, 위 1·3절이 통과했는지 확인
2. 팀 승인 후 한 사람만 실행: `uv run alembic upgrade 0005` (개발 DB). 프론트 담당자와 실행자를 정해 중복 실행을 피합니다.
3. `uv run python -m scripts.verify_dev_environment` → `alembic.current` = 0005
4. 운영 DB는 별도 배포 절차(`ALLOW_PRODUCTION_MIGRATIONS=true`)로만 적용합니다.

## 5. 개발 DB가 준비되지 않았을 때

로컬 PostgreSQL에서 마이그레이션·API 통합 테스트를 실행합니다 (Storage는 메모리 Fake). 원격·Supabase 호스트는 테스트 fixture가 거부합니다.

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/artmate_test uv run pytest
```

Docker가 없는 Windows에서는 `pgserver` 패키지의 PostgreSQL 바이너리(`initdb`, `pg_ctl`)로 임시 클러스터를 띄워도 됩니다 (v0.5.1 검증에 사용).

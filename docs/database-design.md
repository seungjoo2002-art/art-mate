# ART MATE 데이터베이스 설계

> 상태: **v0.4 구현 반영** (§3.9 작품·사진, §3.10 시험 타이머, 리비전 `0003`). §3.1~3.3a(`profiles`, `academies`, `academy_memberships`, `academy_join_requests`)는 리비전 `0001`, §3.6(반·일정·출석·주제·과제·개인 할 일 10개 테이블)은 리비전 `0002`로 구현했습니다. 나머지 엔티티는 설계안이며, 구현할 때 이 문서를 함께 수정합니다.

## 1. 공통 규칙

| 항목 | 규칙 |
| --- | --- |
| DB | Supabase PostgreSQL, 앱 테이블은 `public` 스키마 |
| 테이블명 | snake_case 복수형 (`academies`, `artwork_stages`) |
| PK | `id uuid` (앱에서 uuid4 생성, `UUIDPrimaryKeyMixin`). 예외: `profiles.id` = `auth.users.id` |
| 시각 | `timestamptz`, UTC 저장. 모든 테이블에 `created_at`, `updated_at` (`TimestampMixin`) |
| 학원 격리 | 학원 소유 데이터는 **모든 테이블에 `academy_id NOT NULL`** (자식 테이블도 비정규화해서 보유) |
| 삭제 | 기본 soft delete(`deleted_at`) 또는 상태값. 물리 삭제는 보존기간 만료·법적 요청 시 배치로 수행 |
| enum | PostgreSQL native enum 대신 `varchar(20) + CHECK`, 값은 대문자 (`STUDENT`, `ACTIVE`). `app/db/base.py`의 `enum_column()` 사용 |
| 제약조건 이름 | `app/db/base.py`의 naming convention 사용 (Alembic 리비전 충돌 방지) |
| 파일 | 이미지·음성은 Supabase Storage에 저장, DB에는 `storage_path`와 메타데이터만 |
| JSON | 구조가 자주 바뀌는 데이터(이미지 주석, AI 출력)만 `jsonb`. 검색·조인 대상은 컬럼으로 |

## 2. ERD (개요)

```text
auth.users 1─1 profiles 1─* academy_memberships *─1 academies          (v0.2 구현)
                  │          (role: OWNER/MANAGER/INSTRUCTOR/STUDENT)
                  └─* academy_join_requests *─1 academies           (v0.2 구현)
                                      │
                                      ├─1 student_profiles ─* consent_records
                                      │
academies 1─* classes 1─* class_memberships *─1 academy_memberships        (v0.3 구현, §3.6)
              │   (+ class_schedules, schedule_exceptions, lesson_topics, tasks, attendance_records)
              │
              └─* lessons 1─* artworks *─1 academy_memberships(student)
                     │          ├─* artwork_stages  ─ media_objects (Storage)
                     │          ├─* feedbacks ──────── ai_analyses (draft 출처)
                     │          └─* student_weaknesses *─1 weakness_tags
                     └─* teacher_calls

academy_memberships(student) 1─* assignments, growth_reports, ai_analyses
```

학생·강사를 가리키는 FK는 `profiles`가 아니라 **`academy_memberships.id`** 를 참조합니다.
→ "어느 학원에서의 학생/강사인가"가 FK 자체에 담기고, 학원을 떠나도 기록의 소속이 명확합니다.

## 3. 엔티티

표기: **PK**, FK→대상, `?` = nullable

### 3.1 Profile — `profiles` ✅ v0.2
서비스 사용자 프로필. Supabase Auth 계정과 1:1. **이메일·비밀번호는 저장하지 않음** (Supabase Auth가 관리).

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| **id** | uuid | = `auth.users.id` (JWT `sub`). 앱에서 생성하지 않음 |
| display_name | varchar(50) | 표시 이름. CHECK: 공백만 불가 |
| user_type | varchar(20) | `STUDENT` / `INSTRUCTOR` / `ADMIN` (CHECK). ADMIN은 API로 부여 불가 |
| avatar_path? | varchar(512) | Storage 경로 `avatars/<id>/<파일>` (API에서 본인 경로만 허용) |
| is_active | bool | 기본 true. false면 보호 API 403 `ACCOUNT_DISABLED` |
| created_at, updated_at | timestamptz | |

- 생성: 회원가입 후 프론트엔드가 `POST /api/v1/users/me` 호출. `INSERT ... ON CONFLICT DO NOTHING`이라 **중복·재시도에 안전**합니다. 생성이 실패해도 다음 로그인 때 `GET /users/me` → 404 → 다시 생성하면 복구됩니다. `auth.users` 트리거는 쓰지 않습니다(auth 스키마 변경을 피하고, 사용자 유형 선택을 명시적으로 받기 위해).
- FK `profiles.id → auth.users(id) ON DELETE CASCADE`: 마이그레이션에서 **auth 스키마가 있는 DB(Supabase)에만** 생성합니다. 로컬·CI PostgreSQL에서는 건너뜁니다. Alembic `check`는 이 FK를 비교 대상에서 제외합니다(`alembic/env.py`).
- 삭제: Supabase 계정을 삭제하면 프로필, 소속, 가입 요청이 CASCADE로 삭제되고, `academies.created_by`·`reviewed_by`는 SET NULL이 됩니다. 일반 탈퇴 흐름(익명화)은 v0.3에서 구현합니다(privacy-and-data-policy.md §3.3).
- 인덱스: PK, `ix_profiles_user_type`

### 3.2 Academy — `academies` ✅ v0.2
| 필드 | 타입 | 설명 |
| --- | --- | --- |
| **id** | uuid | |
| name | varchar(100) | 2~100자 (중복 허용: 지역별 동명 학원) |
| description? | varchar(1000) | |
| status | varchar(20) | `PENDING_APPROVAL` → `ACTIVE` / `REJECTED`, (`SUSPENDED`: v0.3 운영 정지) |
| created_by? → profiles | uuid | 등록 신청자 (ON DELETE SET NULL) |
| reviewed_by? → profiles, reviewed_at?, review_note? | | 시스템 ADMIN 심사 기록 |

- 생성 정책: INSTRUCTOR가 신청하면 `PENDING_APPROVAL`, 신청자는 같은 트랜잭션에서 `OWNER` 소속이 됩니다. 시스템 ADMIN이 승인해야 학원 찾기에 노출되고 가입 요청을 받을 수 있습니다.
- 공개 범위: `ACTIVE`는 로그인 사용자 누구나 조회할 수 있습니다. 그 외 상태는 소속 멤버와 시스템 ADMIN만 볼 수 있습니다.
- 삭제: API 없음 (v0.3에서 폐원 처리 정책과 함께)
- 인덱스: `ix_academies_status_name(status, name)` (학원 찾기), `ix_academies_created_by`
- 추후 후보: slug, timezone, 사업자 정보, 지역

### 3.3 AcademyMembership — `academy_memberships` ✅ v0.2
**실제 소속**과 학원별 역할. 권한 판단의 기준. (가입 *요청*은 3.3a로 분리)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| **id** | uuid | |
| academy_id → academies | uuid | ON DELETE CASCADE |
| user_id → profiles | uuid | ON DELETE CASCADE |
| role | varchar(20) | `OWNER` / `MANAGER` / `INSTRUCTOR` / `STUDENT` |
| status | varchar(20) | `ACTIVE` / `LEFT`(본인 탈퇴) / `REMOVED`(관리자 제외) |
| joined_at, left_at? | timestamptz | |

- 한 사용자는 여러 학원에 소속할 수 있지만, **학원당 소속 행은 1개**(`uq(academy_id, user_id)`)입니다. 재가입하면 같은 행을 `ACTIVE`로 재활성화합니다(`INSERT ... ON CONFLICT DO UPDATE WHERE status <> 'ACTIVE'`).
- 역할 규칙(서비스 계층): STUDENT 유형은 STUDENT 역할만 가질 수 있습니다. INSTRUCTOR 유형은 INSTRUCTOR/MANAGER/OWNER, ADMIN 유형은 소속할 수 없습니다.
- 삭제: API로는 물리 삭제하지 않고 상태만 바꿉니다(과거 기록의 작성자 참조 유지).
- 인덱스: `uq_academy_memberships_academy_id_user_id`, `ix_academy_memberships_user_status(user_id, status)` (내 학원), `ix_academy_memberships_academy_status_role` (멤버 목록)
- v0.3: 자식 테이블의 교차 학원 연결 방지를 위해 `uq(academy_id, id)` 추가 (복합 FK 대상, §3.6)

### 3.3a AcademyJoinRequest — `academy_join_requests` ✅ v0.2
학원 가입 요청 이력. 소속 상태와 섞지 않습니다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| **id** | uuid | |
| academy_id → academies, user_id → profiles | uuid | ON DELETE CASCADE |
| requested_role | varchar(20) | `STUDENT` / `INSTRUCTOR`만 (CHECK `requested_role_allowed`). 사용자 유형에서 결정 |
| status | varchar(20) | `PENDING` → `APPROVED` / `REJECTED` |
| message? | varchar(300) | 신청 메시지 |
| reviewed_by? → profiles, reviewed_at?, review_note? | | 처리한 관리자 (ON DELETE SET NULL) |

- **중복 방지**: 부분 유니크 인덱스 `uq_academy_join_requests_pending (academy_id, user_id) WHERE status = 'PENDING'`. 동시 요청도 DB가 막고 API는 409를 반환합니다. 거절·승인된 요청은 이력으로 남고, 다시 신청할 수 있습니다.
- **승인 동시성**: 처리할 때 요청 행을 `SELECT ... FOR UPDATE`로 잠급니다. 두 관리자가 동시에 처리해도 한 번만 처리되고, 다른 쪽은 409 `JOIN_REQUEST_ALREADY_REVIEWED`를 받습니다.
- 인덱스: `ix_academy_join_requests_academy_status(academy_id, status, created_at)` (관리자 목록), `ix_academy_join_requests_user(user_id, created_at)` (내 요청)
- 추후: 강사 초대 코드(`academy_invitations`), 요청 취소(`CANCELLED`)

### 3.4 StudentProfile — `student_profiles` *(추가 제안)*
학원 내 학생 정보 (입시 정보, 보호자).

| 필드 | 설명 |
| --- | --- |
| **membership_id** → academy_memberships (PK, 1:1) | |
| academy_id | |
| school_grade? | 학년 |
| target_track? | `art_middle` / `art_high` / `art_college` |
| target_schools? | 지망 학교 (jsonb 배열) |
| guardian_name?, guardian_phone? | 보호자 연락처 (학부모 리포트 발송용) |
| is_minor | 가입 시 계산, 동의 절차 분기용 |

### 3.5 ConsentRecord — `consent_records` *(추가 제안, 미성년자 대응)*
| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, student_membership_id | |
| consent_type | `privacy_collection`, `artwork_photo`, `voice_recording`, `ai_processing`, `guardian_report`, `marketing` |
| granted_by | `self` / `guardian` |
| guardian_name? | 법정대리인 동의 시 |
| policy_version | 동의한 약관 버전 |
| granted_at, revoked_at? | |

- **append-only** (수정 대신 새 레코드). 현재 상태 = 유형별 최신 레코드
- 만 14세 미만은 법정대리인 동의가 필요(개인정보 보호법 제22조의2) → `granted_by=guardian` 필수
- 기능 게이트: `voice_recording` 동의 없으면 녹음 금지, `ai_processing` 동의 없으면 AI 분석 대상 제외
- 인덱스: `ix(student_membership_id, consent_type, granted_at desc)`

### 3.6 v0.3 학원 운영 테이블 ✅ v0.3 (리비전 `0002`)

**공통 원칙**
- 모든 테이블: UUID PK, `created_at`·`updated_at`(timestamptz), **RLS 활성화**(정책 없음, 4.3).
- 학원 소유 테이블은 `academy_id NOT NULL`이고, 부모는 **복합 FK** `(academy_id, <부모 id>) → 부모(academy_id, id)`로 참조합니다. 이를 위해 `academy_memberships`, `classes`, `tasks`, `attendance_records`에 `uq(academy_id, id)`를 두었습니다. → API를 우회해도 다른 학원의 반·학생을 연결하는 행은 DB가 거부합니다.
- 학생·강사 참조는 `academy_memberships.id`(이 문서에서 `*_membership_id`).
- 시간대: 시각은 timestamptz(UTC), 운영 날짜는 `date`(Asia/Seoul 달력 날짜), 정규 수업 시간은 `time`(Asia/Seoul 벽시계). (`app/core/timezone.py`)
- 상태 변경 위주: 반은 `ARCHIVED`, 반 배정은 `REMOVED`, 정규 수업·일정 예외는 `is_active=false`, 과제는 `CANCELLED`. 물리 삭제는 수업 주제·개인 할 일만.

```text
academies 1─* classes 1─* class_memberships *─1 academy_memberships   (role: INSTRUCTOR=담당 강사 | STUDENT)
               │      1─* class_schedules 1─* schedule_exceptions      (CANCELLATION | RESCHEDULE)
               │      1─* schedule_exceptions                          (MAKEUP, 선택: student_membership_id)
               │      1─* lesson_topics
               │      1─* tasks 1─* task_assignments *─1 academy_memberships(student)
academy_memberships(student) 1─* attendance_records 1─* attendance_audit_logs
profiles 1─* personal_todos                                             (학원 데이터 아님)
```

#### `classes` (모델 `AcademyClass`)
| 필드 | 타입 | 설명 |
| --- | --- | --- |
| academy_id → academies | uuid | ON DELETE CASCADE |
| name | varchar(100) | CHECK 공백 불가 |
| description?, subject? | varchar(1000), varchar(50) | |
| status | varchar(20) | `ACTIVE` / `ARCHIVED` |
| created_by? → academy_memberships | uuid | SET NULL |

인덱스: `uq(academy_id, id)`, `ix(academy_id, status, name)`

#### `class_memberships` — 반 배정 + 담당 강사
| 필드 | 설명 |
| --- | --- |
| academy_id, class_id, membership_id | 복합 FK → classes, academy_memberships (CASCADE) |
| role | `INSTRUCTOR`(담당 강사) / `STUDENT`. 학원 역할에서 결정 (STUDENT → STUDENT, 그 외 → INSTRUCTOR) |
| status | `ACTIVE` / `REMOVED` |
| joined_at, ended_at? | |

- `uq(class_id, membership_id)`: (반, 사람)당 1행. 재배정 시 `INSERT … ON CONFLICT DO UPDATE WHERE status <> 'ACTIVE'`로 재활성화 → 동시 배정도 1건만 성공(409 `ALREADY_IN_CLASS`).
- 학원 탈퇴·제외 시 같은 트랜잭션에서 그 사람의 반 배정을 모두 `REMOVED`로 바꿉니다.
- 인덱스: `ix(class_id, status, role)`, `ix(membership_id, status)`

#### `class_schedules` — 정규 수업(매주 반복)
| 필드 | 설명 |
| --- | --- |
| academy_id, class_id | 복합 FK → classes |
| weekday | smallint 0=월…6=일 (CHECK) |
| start_time, end_time | time, CHECK end > start |
| effective_from, effective_until? | date, CHECK until ≥ from |
| location? | |
| is_active | DELETE 시 false |

- 회차를 미리 만들지 않고 조회 시 펼칩니다(`expand_occurrences`). 같은 반의 겹치는 정규 수업은 반 행을 `FOR UPDATE`로 잠근 뒤 검사합니다(409 `SCHEDULE_OVERLAP`).
- 인덱스: `uq(class_id, id)`(예외의 복합 FK 대상), `ix(class_id, is_active)`

#### `schedule_exceptions` — 휴강·1회 변경·보강
| 필드 | 설명 |
| --- | --- |
| academy_id, class_id | 복합 FK → classes |
| schedule_id? | 복합 FK `(class_id, schedule_id)` → class_schedules: 다른 반의 정규 수업 참조 불가 |
| kind | `CANCELLATION` / `RESCHEDULE` / `MAKEUP` (CHECK `kind_fields`로 종류별 필수·금지 필드 강제) |
| original_date? | 대상 정규 회차 날짜 (CANCELLATION, RESCHEDULE) |
| session_date?, start_time?, end_time? | 실제 진행 날짜·시간 (RESCHEDULE, MAKEUP) |
| student_membership_id? | 개인 보강 대상 (MAKEUP만, 복합 FK) |
| location?, reason?, is_active, created_by? | |

- **부분 유니크** `uq_schedule_exceptions_occurrence (schedule_id, original_date) WHERE is_active AND kind IN ('CANCELLATION','RESCHEDULE')`: 한 회차에 유효한 휴강/변경은 1개.
- 인덱스: `ix(class_id, session_date)`, `ix(class_id, original_date)`

#### `attendance_records` — 출석
| 필드 | 설명 |
| --- | --- |
| academy_id, student_membership_id | 복합 FK → academy_memberships |
| attendance_date | date (Asia/Seoul) |
| status | `PRESENT` / `LATE` / `ABSENT` / `EXCUSED` |
| source | `SELF_CHECK_IN` / `INSTRUCTOR`. CHECK: 자가 체크인이면 `checked_in_at` 필수 |
| checked_in_at?, note?, updated_by? → academy_memberships | |

- **중복 출석 방지**: `uq(student_membership_id, attendance_date)` + `INSERT … ON CONFLICT DO NOTHING RETURNING` → 동시 요청도 1건만 저장, 나머지는 409.
- 인덱스: `uq(academy_id, id)`, `ix(academy_id, attendance_date)`

#### `attendance_audit_logs` — 출석 수정 이력 (append-only)
| 필드 | 설명 |
| --- | --- |
| academy_id, attendance_record_id | 복합 FK → attendance_records (CASCADE) |
| action | `CREATED` / `UPDATED` (강사 작업만, 학생 체크인은 기록하지 않음) |
| changed_by? → academy_memberships | SET NULL |
| previous?, current | jsonb `{status, note}` 스냅샷 |
| reason? | |

- 수정은 출석 행을 `FOR UPDATE`로 잠근 뒤 같은 트랜잭션에서 이력을 추가합니다. `created_at`은 잠금 획득 후의 앱 시각으로 넣어 이력 순서 = 실제 변경 순서가 되게 합니다 (DB `now()`는 트랜잭션 시작 시각이라 잠금 대기 순서와 다를 수 있음).
- 인덱스: `ix(attendance_record_id, created_at)`

#### `lesson_topics` — 수업 주제
academy_id, class_id(복합 FK), lesson_date, title(200), description?(2000), created_by?. `uq(class_id, lesson_date)`. 미래 날짜 = 다음 수업 사전 공지.

#### `tasks` / `task_assignments` — 학원 과제 (주제와 별도 테이블)
| `tasks` | 설명 |
| --- | --- |
| academy_id, class_id | 복합 FK → classes |
| lesson_topic_id? → lesson_topics | SET NULL (주제 삭제 시 과제는 유지) |
| title, description?, due_at? | due_at timestamptz |
| target_type | `CLASS` / `STUDENTS` |
| status, cancelled_at? | `ACTIVE` / `CANCELLED` |
| created_by? | |

| `task_assignments` | 설명 |
| --- | --- |
| academy_id, task_id, student_membership_id | 복합 FK → tasks, academy_memberships |
| completed_at? | null = 미완료. 학생 본인만 변경 |

- 대상 학생은 배포 시점에 확정(반 행 잠금 후 반 학생 조회 → 과제 + 배정을 한 트랜잭션으로 저장).
- 집계(완료 수, 미완료 수)는 반 배정·학원 소속이 ACTIVE인 학생의 배정만 셉니다.
- 인덱스: `uq(academy_id, id)`, `ix(class_id, status, created_at)`, `ix(academy_id, created_at)`, `uq(task_id, student_membership_id)`, `ix(student_membership_id, completed_at)`
- 3.13의 AI 추천 과제(`origin`, `ai_analysis_id`, 제출·검토 상태)는 이후 버전에서 이 테이블을 확장합니다.

#### `personal_todos` — 학생 개인 할 일 (학원 데이터 아님)
user_id → profiles (CASCADE), title, note?, due_date?(date), completed_at?. 인덱스 `ix(user_id, due_date)`.
`academy_id`가 없어 학원 API·강사 권한과 완전히 분리됩니다. 모든 쿼리에 `user_id = 토큰 사용자` 조건.

### 3.8 Lesson — `lessons` (실기 수업 회차) *(이후 버전 설계안)*

> v0.3의 수업 일정은 `class_schedules` + `schedule_exceptions`(조회 시 회차 계산)로 구현했습니다. 실기 타이머·작품 연결이 필요한 버전에서 회차를 실체화할 때 아래 설계를 다시 검토합니다.

| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, class_id? | 반 수업 또는 개별 수업 |
| teacher_id → academy_memberships | |
| topic? | 그날의 주제/문제 (예: "석고 아그리파 4시간") |
| scheduled_start, scheduled_end | |
| started_at?, ended_at? | 실제 진행 (실기 타이머 기준) |
| status | `scheduled` / `in_progress` / `finished` / `cancelled` |

- 인덱스: `ix(academy_id, scheduled_start)`, `ix(class_id, scheduled_start)`

### 3.9 v0.4 작품·단계 사진 ✅ v0.4 (리비전 `0003`)

#### `artworks`
| 필드 | 설명 |
| --- | --- |
| owner_id → profiles | 작품 소유 학생 (CASCADE). **학원 미소속 학생도 생성 가능** |
| academy_id?, student_membership_id? | 학원 연결(선택). 3열 복합 FK `(academy_id, student_membership_id, owner_id) → academy_memberships(academy_id, id, user_id)`: 본인의 그 학원 소속만 연결 가능 |
| class_id?, task_id? | 복합 FK `(academy_id, class_id)`, `(academy_id, task_id)` → 다른 학원 반·과제 연결 불가 |
| title, description?, work_date | work_date = Asia/Seoul 날짜 |
| deleted_at? | soft delete |

- CHECK: `academy_id`와 `student_membership_id`는 함께 null/not null, 학원 없이 반·과제 연결 불가.
- 학원 연결 FK는 NO ACTION: 학원·소속 행을 물리 삭제하려면 작품과 Storage 파일을 먼저 처리해야 합니다(고아 파일 방지).
- 진행 상태(`NOT_STARTED/SKETCH/PROGRESS/FINAL`)는 저장하지 않고 ACTIVE 사진에서 계산합니다.
- 인덱스: `ix(owner_id, work_date)`, `ix(academy_id, student_membership_id, work_date)`, `uq(id, owner_id)`(사진 복합 FK 대상)

#### `artwork_photos`
| 필드 | 설명 |
| --- | --- |
| artwork_id, owner_id | 복합 FK → artworks(id, owner_id) CASCADE. owner_id는 Storage 정책 판단용 비정규화 |
| stage | `SKETCH` / `PROGRESS` / `FINAL` |
| status | `PENDING`(업로드 URL 발급) → `ACTIVE`(검증 완료) → `DELETED` |
| storage_path (unique) | `{owner_id}/{artwork_id}/{photo_id}.{ext}` — 서버가 생성, 사용자 파일명 미사용 |
| content_type, size_bytes?, width?, height?, sha256? | ACTIVE면 필수 (CHECK `active_has_metadata`) |
| is_representative | 단계 대표 사진 |
| upload_expires_at, uploaded_at?, deleted_at? | |
| replaces_photo_id? | 교체 업로드 대상 |
| storage_cleanup_pending | DB는 DELETED인데 Storage 파일 삭제 미확인 → 다음 요청에서 재시도 |

- 부분 유니크: 단계별 대표 1장 `uq(artwork_id, stage) WHERE is_representative`, 같은 파일 중복 방지 `uq(artwork_id, sha256) WHERE status = 'ACTIVE'`.
- DB·Storage 일관성: ACTIVE 전환은 Storage에서 파일을 받아 검증한 뒤에만, 삭제는 DB 먼저(cleanup 플래그) → Storage 삭제.
- 파일은 Supabase Storage 비공개 버킷 `artworks`. DB에는 경로·메타데이터만 저장합니다.

#### Storage 권한 (`artmate_private.can_access_artwork_object`)
- `backend/supabase/storage-setup.sql`의 `storage.objects` RLS 정책이 호출하는 SECURITY DEFINER 함수입니다. Data API에 노출되지 않는 `artmate_private` 스키마에 있고, search_path를 고정했으며 PUBLIC 실행 권한은 회수했습니다.
- write(업로드·삭제): 사진 행 소유자 + 경로 첫 폴더 = 본인. read: 소유자, 또는 학원 연결 작품의 담당 강사·학원 관리자(학생 소속 ACTIVE).
- 백엔드는 service_role 키 없이 사용자 토큰으로 Storage를 호출하므로 이 정책이 2차 방어가 됩니다.

### 3.10 v0.4 시험 타이머 ✅ v0.4 (리비전 `0003`)

| 테이블 | 주요 필드 · 제약 |
| --- | --- |
| `exam_templates` | academy_id(CASCADE), name, exam_type(자유 입력), description?, total_minutes(1~720), is_archived, created_by?. `uq(academy_id, id)` |
| `exam_stage_targets` | (academy_id, template_id) 복합 FK, stage, offset_minutes(시작 후 분). `uq(template_id, stage)` |
| `exam_sessions` | (academy_id, class_id) 복합 FK, template_id?(SET NULL), title·exam_type·total_minutes 스냅샷, status `SCHEDULED/RUNNING/ENDED/CANCELLED`, started_at·ends_at·ended_at, end_reason `MANUAL/TIME_UP`, created_by/started_by/ended_by. **부분 유니크 `uq(class_id) WHERE status = 'RUNNING'`**(반당 진행 중 1개) |
| `exam_session_stages` | 세션별 단계 목표 스냅샷: offset_minutes, target_at(시작 시 저장). `uq(session_id, stage)` |
| `exam_participants` | (academy_id, session_id), (academy_id, student_membership_id) 복합 FK, current_stage `NOT_STARTED/SKETCH/PROGRESS/FINAL/DONE`, 단계별 최초 진입 시각. `uq(session_id, student_membership_id)` |

- 서버는 시작·종료 예정·단계 목표 시각만 저장하고, 남은 시간은 매 응답에서 서버 시각으로 계산합니다(`app/services/exam_timer.py`).
- `ends_at`이 지나면 응답은 ENDED(TIME_UP), DB 반영은 다음 쓰기 작업(종료·단계 변경·같은 반 새 시험 시작)에서 합니다.
- 세션은 생성 시 템플릿을 복사하므로 템플릿을 수정해도 기존 세션에는 영향이 없습니다.

### 3.11 Feedback — `feedbacks` (강사 첨삭)
| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, artwork_id, artwork_stage_id? | 특정 단계 사진에 대한 첨삭 |
| student_id, teacher_id → academy_memberships | |
| origin | `teacher` (직접 작성) / `ai_assisted` (AI 초안을 강사가 수정·확정) |
| ai_analysis_id? → ai_analyses | AI 초안 출처 |
| body | 확정된 첨삭 내용 |
| annotations | jsonb: 이미지 주석 `[{type: "arrow"|"circle"|"freehand"|"text", points: [[x,y]...], color, text}]`, 좌표는 0~1 정규화 |
| audio_path? | 첨삭 음성 원본 (Storage) |
| status | `draft` / `published` |
| published_at? | |

- **AI 결과와 확정 피드백의 구분**: 이 테이블에는 강사가 확정한 내용만 저장합니다. AI 원문은 `ai_analyses`에 남고, 학생·학부모에게는 `status=published`만 노출
- 인덱스: `ix(artwork_id, created_at)`, `ix(academy_id, student_id, published_at desc)`

### 3.12 TeacherCall — `teacher_calls` (강사 호출·대기열)
| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, lesson_id, student_id, artwork_id? | |
| status | `waiting` / `accepted` / `resolved` / `cancelled` |
| note? | 학생 메모 ("명암 질문") |
| requested_at, accepted_at?, resolved_at? | |
| accepted_by? → academy_memberships | |

- 대기열 = `WHERE lesson_id=? AND status='waiting' ORDER BY requested_at`
- 인덱스: `ix(lesson_id, status, requested_at)`, **부분 유니크** `uq(lesson_id, student_id) WHERE status IN ('waiting','accepted')` (중복 호출 방지 → 409 `CONFLICT`)
- 실시간 알림은 Supabase Realtime 또는 SSE 검토 (향후)
- 보존: 통계 집계 후 90일 이후 삭제 가능

### 3.13 Assignment — `assignments` *(v0.3 `tasks`/`task_assignments`로 1차 구현, AI 추천 필드는 이후 확장)*
| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, student_id | |
| created_by → academy_memberships | 출제 강사 |
| origin | `teacher` / `ai_recommended` (강사 승인 후 학생에게 노출) |
| ai_analysis_id? | 추천 근거 |
| title, description, due_at? | |
| weakness_tag_ids? | 목표 약점 (jsonb 배열 또는 연결 테이블) |
| status | `proposed` / `assigned` / `submitted` / `reviewed` / `cancelled` |

- 인덱스: `ix(academy_id, student_id, status)`

### 3.14 WeaknessTag — `weakness_tags`
| 필드 | 설명 |
| --- | --- |
| **id**, academy_id? | null = 시스템 공통 태그, 값 = 학원 전용 태그 |
| code, name | 예: `proportion`(비례), `value_contrast`(명암 대비), `composition`(구도), `edge_control` |
| category | `form` / `value` / `color` / `composition` / `texture` / `completion` |
| is_active | |

- 인덱스: `uq(academy_id, code)` (+ 공통 태그용 `uq(code) WHERE academy_id IS NULL`)

### 3.15 StudentWeakness — `student_weaknesses`
작품/첨삭에서 관찰된 약점 1건 (반복 약점 분석의 원천 데이터).

| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, student_id, weakness_tag_id | |
| artwork_id?, feedback_id? | 근거 |
| severity | 1~5 |
| origin | `teacher` / `ai` |
| confirmed_by? | AI 판단은 강사 확인 전까지 분석에서 가중치 낮게 |
| observed_at | |

- "반복 약점" = 기간 내 같은 태그 빈도·심각도 집계 → 리포트·과제 추천 입력
- 인덱스: `ix(student_id, weakness_tag_id, observed_at)`, `ix(academy_id, observed_at)`

### 3.16 AIAnalysis — `ai_analyses`
모든 AI 호출의 입력 참조·출력·상태 기록 (감사·재현·비용 추적).

| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, student_id? | |
| kind | `stt` / `feedback_summary` / `weakness_analysis` / `assignment_recommendation` / `growth_summary` |
| target_type, target_id | 대상 (artwork, feedback, report 등) |
| status | `pending` / `processing` / `completed` / `failed` |
| provider, model, prompt_version | 재현성 |
| input_refs | jsonb: 사용한 Storage 경로·레코드 ID (원문 개인정보 복제 금지) |
| output | jsonb: AI 결과 원문 (**확정본 아님**) |
| error_code? | 실패 사유 코드 (상세는 로그) |
| usage | jsonb: 토큰·처리 시간·비용 |
| requested_by → academy_memberships | |
| completed_at? | |

- 인덱스: `ix(academy_id, kind, created_at)`, `ix(target_type, target_id)`, `ix(status) WHERE status IN ('pending','processing')`
- 보존: STT 원문 transcript는 첨삭 확정 후 일정 기간 뒤 삭제 가능

### 3.17 GrowthReport — `growth_reports`
| 필드 | 설명 |
| --- | --- |
| **id**, academy_id, student_id | |
| period_start, period_end | |
| content | jsonb (요약, 대표 작품 ID, 약점 추이 지표) |
| ai_analysis_id? | 초안 출처 |
| status | `draft` / `published` |
| created_by, published_at?, shared_with_guardian_at? | |

- 인덱스: `ix(academy_id, student_id, period_end desc)`

### 3.18 MediaObject — `media_objects` *(추가 제안)*
Storage 객체 메타데이터를 한 곳에서 관리 → 권한 확인·보존기간·삭제를 일관되게 처리.

| 필드 | 설명 |
| --- | --- |
| **id**, academy_id | |
| bucket, storage_path (unique) | |
| purpose | `artwork_image` / `feedback_audio` / `report_pdf` |
| owner_student_id? | 접근 권한 판단 |
| content_type, size_bytes | |
| retention_until? | 이 시각 이후 삭제 배치 대상 |
| deleted_at? | |

## 4. 학원별 데이터 격리

### 4.1 원칙
1. 학원 소유 테이블은 모두 `academy_id NOT NULL`
2. 모든 보호 API는 경로에 `academy_id`를 받고 → `academy_memberships`로 **요청자가 그 학원의 active 멤버인지** 확인 → 역할 확인
3. 리포지토리의 모든 조회는 `academy_id` 조건을 포함 (ID만으로 조회 금지)
   ```python
   select(Artwork).where(Artwork.academy_id == academy_id, Artwork.id == artwork_id)
   ```
4. 다른 학원 리소스 접근은 **404** (존재 여부 비노출)
5. 복합 FK `(academy_id, student_id) → academy_memberships(academy_id, id)` 로 교차 학원 연결을 DB가 거부

### 4.2 역할별 접근 범위

v0.2 구현 (학원 내 역할 기준, 시스템 ADMIN은 학원 소속이 아니면 접근 불가)

| 리소스 | OWNER | MANAGER | INSTRUCTOR | STUDENT |
| --- | --- | --- | --- | --- |
| 학원 정보 | 읽기 | 읽기 | 읽기 | 읽기 |
| 멤버 목록 | 읽기 | 읽기 | 읽기 | ❌ (다른 학생 정보 보호) |
| 가입 요청 목록·승인·거절 | ✅ | ✅ | ❌ | ❌ |
| 멤버 제외 | ✅ (OWNER 제외 불가) | ✅ (OWNER·MANAGER 제외 불가) | ❌ | ❌ |
| MANAGER 지정·해제 | ✅ | ❌ | ❌ | ❌ |
| 학원 탈퇴 | ❌ | ✅ | ✅ | ✅ |

v0.3 구현 (admin = OWNER/MANAGER, teacher = INSTRUCTOR 이상, 담당 = class_memberships의 담당 강사)

| 리소스 | admin | teacher (담당 반) | teacher (비담당) | student |
| --- | --- | --- | --- | --- |
| 반 생성·수정·보관, 담당 강사 지정 | ✅ | ❌ | ❌ | ❌ |
| 반·정규 수업·수업 주제 읽기 | 전체 | 전체 | 전체 | 배정된 반만 (그 외 404) |
| 학생 배정, 일정·휴강·보강, 주제, 과제 쓰기 | ✅ | ✅ | 403 | 403/404 |
| 출석 현황·기록·수정·이력 | 모든 학생 | 담당 학생 | 403 / 빈 목록 | 본인 기록 읽기, 체크인 |
| 과제 완료 현황 | 전체 | 담당 반 | 403 | 본인 배정만, 완료 체크 |
| 개인 할 일 | ❌ | ❌ | ❌ | 본인만 (`/personal-todos`) |
| 대시보드 | 전체 / 담당 반 | 담당 반 | 빈 화면 | ❌ |

구현: `app/services/access.py` (담당 반·담당 학생 판단 쿼리를 한 곳에 모음)

이후 버전 설계안

| 리소스 | admin | teacher | student |
| --- | --- | --- | --- |
| 작품·단계 사진 | 전체 읽기 | 전체 읽기 (v0.x에서 담당 반 한정 검토) | **자기 작품만** 읽기/업로드 |
| 첨삭 | 전체 읽기 | 작성/수정 (본인 작성분) | 자기 작품의 `published`만 |
| AI 분석 원문 | 읽기 | 읽기/요청 | 접근 불가 |
| 강사 호출 | 읽기 | 수락/해결 | 생성/취소 (본인) |
| 성장 리포트 | 읽기/발행 | 작성 | `published`만 |
| 동의 기록 | 읽기 | 읽기 | 자신만 |

### 4.3 Supabase RLS 적용 방향

Supabase는 `public` 스키마를 Data API(PostgREST)로 노출하며 anon key는 공개 값입니다. 따라서:

1. **모든 앱 테이블에 RLS를 켭니다** (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`). `anon`·`authenticated`에 대한 정책이 없으면 기본 거부 → anon key로 테이블 직접 조회 불가. 테이블 생성 마이그레이션에 RLS 활성화를 함께 포함합니다.
2. **1차 방어는 API 서버**(4.1). 백엔드는 `DATABASE_URL`의 DB 역할로 접속하는데, 테이블 소유자나 `BYPASSRLS` 역할이면 RLS가 적용되지 않습니다. 그래서 애플리케이션 계층의 격리 규칙을 생략하면 안 됩니다.
3. **심층 방어 (v0.3 이후 검토)**: 백엔드 전용 DB 역할(`artmate_api`, 비소유자, `NOBYPASSRLS`)을 만들고, 요청 트랜잭션 시작 시 `SELECT set_config('app.user_id', :uid, true)`로 사용자 ID를 주입, 정책은 `security definer` 함수 `app.is_academy_member(academy_id, roles[])`로 판단. `set_config(..., true)`는 트랜잭션 범위라 transaction pooler와도 호환됩니다.
4. 프론트엔드가 Supabase를 직접 읽는 기능(예: 강사 호출 Realtime 구독)을 도입하면 그 테이블에만 `authenticated` 정책을 명시적으로 작성합니다: `using (app.is_academy_member(academy_id) )` + `auth.uid()` 기반 본인 조건.
5. **Storage**: 버킷은 private. 경로를 `academies/{academy_id}/...`로 고정하고 `storage.objects` 정책에서 경로의 academy_id와 멤버십으로 판단합니다. 백엔드는 사용자의 access token으로 Storage API를 호출하거나(사용자 권한으로 동작), 권한 확인 후 짧은 만료(예: 5분)의 signed URL을 발급합니다.
6. **service_role 키 금지 원칙**: API 서버에 service_role 키를 두지 않습니다(이 키는 모든 RLS를 우회). 보존기간 만료 파기처럼 꼭 필요한 관리 작업은 API와 분리된 배치 작업에서만, 별도 키와 감사 로그와 함께 사용합니다.

## 5. 인증·권한 고려사항

- `profiles.id = auth.users.id = JWT sub` → 토큰 검증 후 추가 매핑 없이 사용자 식별
- 역할은 JWT가 아니라 `academy_memberships.role`에서 조회 (학원마다 다르고, 변경이 즉시 반영돼야 함)
- 학원 합류(v0.2): 본인 가입 요청 → OWNER/MANAGER 승인 (`academy_join_requests`). 강사 초대 코드는 v0.3 이후
- 상세 정책: architecture.md §5, 개인정보·삭제 정책: privacy-and-data-policy.md
- 학원 선택: 클라이언트가 현재 학원을 경로의 `academy_id`로 전달 (서버 세션 상태 없음)
- 미성년 학생: `student_profiles.is_minor`와 `consent_records`로 기능 게이트, 보호자 연락처는 리포트 발송에만 사용

## 6. 개인정보·파일 보존 정책 (초안, 학원과 협의 필요)

| 데이터 | 기본 정책 |
| --- | --- |
| 첨삭 원본 음성 | 첨삭 확정 후 30일 보존 후 삭제 (`media_objects.retention_until`) |
| STT transcript | 첨삭 확정 후 90일 (확정 첨삭 본문은 유지) |
| 작품 이미지 | 학생 재원 기간 + 퇴원 후 1년, 이후 삭제 또는 학생 요청 시 즉시 삭제 |
| AI 분석 원문 | 1년 후 output 삭제(메타데이터·사용량만 유지) |
| 탈퇴 사용자 | 즉시 프로필 익명화, 관련 파일은 위 정책에 따라 삭제 |
| 동의 기록 | 삭제하지 않음 (증빙) |

- 원본 파일 접근: 학생 본인, 소속 학원의 강사·관리자만. 학부모는 발행된 리포트로만 접근
- 모든 파일 URL은 signed URL(짧은 만료), public URL 사용 금지

## 7. 마이그레이션 운영

1. 모델 추가/수정 → `app/models/__init__.py`에 import
2. `uv run alembic revision --autogenerate -m "..."` → **생성된 파일 직접 검토** (RLS 활성화, cross-schema FK, 부분 인덱스 등은 수동 추가)
3. 개발 DB에서 `upgrade head` → `downgrade -1` → `upgrade head` 로 왕복 확인
4. PR 리뷰 후 merge. 운영 적용은 사람이 명시적으로 (`ALLOW_PRODUCTION_MIGRATIONS=true`)
5. 두 개발자가 동시에 리비전을 만들면 head가 2개가 됩니다 → 나중에 merge하는 쪽이 `down_revision`을 최신 head로 수정(또는 `alembic merge`) (→ development-guide.md)

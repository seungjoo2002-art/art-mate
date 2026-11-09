# 프론트엔드 연동 가이드 (v0.8 F-15 참고작 추천 · 커뮤니티)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.8
> 선행 문서: [frontend-integration.md](frontend-integration.md) (인증·`api()`·오류 형식), [v0.7](frontend-integration-v0.7.md) (반복 약점)
> 설계: [reference-community-v0.8.md](reference-community-v0.8.md) · API 문서: http://127.0.0.1:8000/docs

## 0. 한눈에

```text
[학생 대시보드] 반복 약점 TOP 3 (v0.7 GET /growth/me/weaknesses)
   → 참고작 추천 POST /references/me/refresh → GET /references/me?category=PROPORTION
   → 추천 이유(reasons) · 강사 참고 포인트(reference_point) · 공유 이미지
   → (있으면) 커뮤니티 게시물 상세 GET /community/posts/{community_post_id}
   → 저장 PUT /references/me/{id}/save → GET /references/me/saved
```

- 작품은 **기본 비공개**입니다. 학생이 작품별로 **커뮤니티 게시(COMMUNITY)** 와 **참고작 활용(REFERENCE)** 을 따로 동의해야 다른 사람에게 보입니다.
- 공유 화면의 이미지는 **원본이 아니라 공유용 이미지**(긴 변 1600px, 촬영 정보·위치 제거)입니다. URL은 짧게 만료되므로 저장하지 말고, 만료되면 목록·상세를 다시 불러오세요.
- 원작자가 공유를 철회하면 피드·추천·저장 목록에서 **즉시** 사라집니다.

## 1. 작품 공유 동의 화면

```http
GET    /api/v1/artworks/{artwork_id}/sharing                 공유 상태
PUT    /api/v1/artworks/{artwork_id}/sharing/COMMUNITY       커뮤니티 게시 동의·변경
PUT    /api/v1/artworks/{artwork_id}/sharing/REFERENCE       참고작 활용 동의·변경
DELETE /api/v1/artworks/{artwork_id}/sharing/{purpose}       철회 (공유 중단)
GET    /api/v1/artworks/{artwork_id}/sharing/history         동의 이력
```

```json
// PUT /artworks/{id}/sharing/COMMUNITY
{ "scope": "PLATFORM",              // ACADEMY: 작품이 연결된 학원 멤버만 / PLATFORM: ART MATE 사용자 전체
  "author_display": "ANONYMOUS",    // NAME: 내 표시 이름 / ANONYMOUS: '익명 학생'
  "policy_version": "2026-11-share-v1",
  "agreed": true,
  "granted_by": "SELF" }            // 만 14세 미만: 법정대리인 확인 후 "GUARDIAN"

// → 200 SharingStatus
{
  "artwork_id": "a1…",
  "required_version": "2026-11-share-v1",
  "community": { "id": "c1…", "purpose": "COMMUNITY", "scope": "PLATFORM", "academy_id": null,
                 "author_display": "ANONYMOUS", "policy_version": "2026-11-share-v1", "granted_by": "SELF",
                 "granted_at": "…", "revoked_at": null, "revoked_reason": null },
  "reference": null,
  "image": { "image_id": "i1…", "url": "https://…/object/sign/shared-artworks/…", "url_expires_at": "…",
             "width": 1600, "height": 1067 },
  "post_id": null
}
```

- 조건: 작품에 **FINAL 대표 사진**이 있어야 합니다 (409 `FINAL_PHOTO_REQUIRED`). `ACADEMY`는 학원에 연결된 작품만 (422 `SHARING_SCOPE_INVALID`).
- 범위·작성자 표시를 바꾸려면 같은 PUT을 다시 보내면 됩니다 (이력에 `CHANGED`로 남음).
- 철회 결과: COMMUNITY → 게시물 삭제, REFERENCE → 다른 학생의 추천·저장에서 제거, 둘 다 없으면 공유 이미지 삭제.

동의 화면에 표시할 내용 (법적 검토 전 초안)
- 목적별 설명: "커뮤니티에 작품 게시" / "다른 학생에게 참고작으로 추천(강사가 우수 사례로 확인한 경우)"
- 공개 범위와 작성자 표시 선택 (기본: 익명)
- 공개되는 것: 공유용 이미지, 게시물 제목·설명(커뮤니티), 실기 유형·작품 분류, 강사의 참고 포인트(참고작). **원본 사진·작품 제목(참고작)·학원명·연락처는 공개되지 않음**
- 언제든 철회 가능, 철회하면 즉시 비공개
- 만 14세 미만은 보호자 동의 필요

## 2. 참고작 추천 (학생)

```http
POST /api/v1/references/me/refresh              새로고침 (입력이 같으면 기존 결과, refreshed=false)
GET  /api/v1/references/me?category=PROPORTION  현재 추천 (약점별 필터)
GET  /api/v1/references/me/{reference_id}       상세
PUT  /api/v1/references/me/{reference_id}/save  저장  /  DELETE … 저장 해제
GET  /api/v1/references/me/saved                저장한 참고작
```

```json
// GET /references/me
{
  "status": "READY",                          // READY · NO_VERIFIED_REFERENCES · NO_REPEATED_WEAKNESS · NOT_GENERATED
  "message": null,
  "weaknesses": ["PROPORTION", "VALUE"],      // 추천 기준 (v0.7 반복 약점 TOP 3)
  "practical_type": "BASIC_DESIGN",
  "generated_at": "2026-11-09T14:50:03Z",
  "removed_count": 0,                         // 원작자 철회 등으로 빠진 수
  "items": [ {
    "id": "r1…",
    "weakness_category": "PROPORTION", "weakness_label": "비례", "weakness_rank": 1, "rank": 1,
    "reasons": [
      { "code": "VERIFIED_EXEMPLAR",   "message": "'비례' 표현의 참고 사례로 강사가 확인한 작품입니다." },
      { "code": "MATCHES_WEAKNESS",    "message": "최근 첨삭에서 반복된 '비례' 약점과 관련된 사례입니다." },
      { "code": "SAME_PRACTICAL_TYPE", "message": "현재 연습 중인 '기초디자인' 유형과 일치합니다." },
      { "code": "SAME_WORK_CATEGORY",  "message": "자주 하는 '모의시험' 작업과 같은 분류의 작품입니다." }
    ],
    "reference_point": "기준선으로 비율을 잡은 방식 참고",     // 강사가 남긴 '어떤 부분을 참고하면 좋은지'
    "reviewed_at": "…",
    "practical_type": "BASIC_DESIGN", "work_category": "MOCK_EXAM",
    "author": { "display_name": "익명 학생", "is_anonymous": true, "is_me": false },
    "image": { "image_id": "…", "url": "https://…", "url_expires_at": "…", "width": 1600, "height": 1067 },
    "community_post_id": "p1…",               // 볼 수 있는 게시물이 있으면 '게시물 보기'
    "saved": false,
    "created_at": "…"
  } ]
}
```

### 참고작 카드

| 영역 | 데이터 |
| --- | --- |
| 이미지 | `image.url` (만료 시 목록 재조회) |
| 라벨 | "비례 참고작" (`weakness_label`), 실기 유형 칩 |
| 추천 이유 | `reasons[].message`를 목록으로 (첫 줄은 항상 강사 확인 사실) |
| 참고 포인트 | `reference_point` ("강사의 한마디") |
| 작성자 | `author.display_name` |
| 버튼 | 저장(`saved` 토글), 게시물 보기(`community_post_id`가 있을 때) |

### 결과가 없을 때

| status | 화면 문구 (예) | 행동 |
| --- | --- | --- |
| `NOT_GENERATED` | — | 화면 진입 시 `POST /refresh` 자동 호출 |
| `NO_REPEATED_WEAKNESS` | `message` 그대로 ("반복 약점이 아직 없습니다…") | 성장 화면으로 |
| `NO_VERIFIED_REFERENCES` | "지금 약점에 맞는, 강사가 확인한 참고작이 아직 없습니다." | 커뮤니티 피드 둘러보기 링크 |

> 참고작은 **강사가 우수 사례로 확인했고 원작자가 동의한 작품만** 나옵니다. 비슷해 보이는 작품을 임의로 채우지 않습니다.

## 3. 강사: 우수 사례 확인

```http
GET    /api/v1/academies/{academy_id}/references/candidates?category=PROPORTION   후보 (승인 첨삭에서 '잘한 점'으로 언급)
POST   /api/v1/academies/{academy_id}/references/reviews      { "artwork_id", "category", "note" }
GET    /api/v1/academies/{academy_id}/references/reviews?category&student_membership_id&status=ACTIVE
DELETE /api/v1/academies/{academy_id}/references/reviews/{review_id}             확인 해제
```

- 담당 학생의 **학원 연결 작품**만, FINAL 사진이 있어야 합니다. 같은 작품·카테고리 중복 409 `REFERENCE_REVIEW_EXISTS`.
- 응답의 `reference_consent`가 `null`이면 "학생이 참고작 활용에 동의하지 않아 추천에 쓰이지 않아요" 안내.
- `note`는 학생 화면의 "참고 포인트"로 보입니다 (500자).

## 4. 커뮤니티

```http
GET    /api/v1/community/posts?practical_type&work_category&academy_id&limit&offset   피드 (최신순)
POST   /api/v1/community/posts                    { artwork_id, title, body?, practical_type?, work_category? }
GET    /api/v1/community/posts/me                 내 게시물 (숨김 포함)
GET    /api/v1/community/posts/{id}
PATCH  /api/v1/community/posts/{id}               { title?, body?, practical_type?, work_category? }
DELETE /api/v1/community/posts/{id}               (동의는 유지 → 다시 게시 가능)
PUT|DELETE /api/v1/community/posts/{id}/like
PUT|DELETE /api/v1/community/posts/{id}/bookmark
GET    /api/v1/community/bookmarks
GET    /api/v1/community/posts/{id}/comments      (오래된 순)
POST   /api/v1/community/posts/{id}/comments      { "body": "…" }   (1~1000자)
PATCH|DELETE /api/v1/community/comments/{id}      (작성자만)
POST   /api/v1/community/posts/{id}/reports       { "reason": "SPAM", "detail": "…" }
POST   /api/v1/community/comments/{id}/reports
```

```json
// PostRead
{
  "id": "p1…",
  "artwork_id": null,                 // 내 게시물일 때만 작품 ID
  "title": "정물 기초디자인", "body": "명암 대비를 신경 썼어요",
  "practical_type": "BASIC_DESIGN", "work_category": "MOCK_EXAM",
  "author": { "display_name": "익명 학생", "is_anonymous": true, "is_me": false },
  "image": { "image_id": "…", "url": "https://…", "url_expires_at": "…", "width": 1600, "height": 1067 },
  "visibility": { "scope": "ACADEMY", "academy_id": "ac…" },
  "like_count": 3, "comment_count": 2, "liked": true, "bookmarked": false,
  "status": "ACTIVE",                 // 내 게시물: HIDDEN이면 hidden_reason 표시
  "hidden_reason": null,
  "created_at": "…", "updated_at": "…"
}
// PUT /like → { "post_id": "p1…", "liked": true, "like_count": 4 }
// CommentRead → { "id", "post_id", "body", "author": { "display_name": "앨리스", "is_anonymous": false, "is_me": true }, "status", "created_at", "updated_at" }
```

- 게시는 학생 본인 작품만, 그 작품의 COMMUNITY 동의가 있어야 합니다 (409 `SHARING_CONSENT_REQUIRED` → 공유 동의 화면). 작품당 1개 (409 `POST_ALREADY_EXISTS`).
- 좋아요·저장은 여러 번 눌러도 1번만 반영됩니다 (응답의 `like_count`로 갱신).
- 댓글 작성자는 항상 표시 이름으로 보입니다 (게시물 익명 설정과 별개).
- 신고 사유: `SPAM` 스팸·광고, `ABUSE` 욕설·괴롭힘, `INAPPROPRIATE` 부적절, `COPYRIGHT` 도용, `PRIVACY` 개인정보 노출, `OTHER`.
- 서로 다른 사용자 신고가 3건 쌓이면 자동으로 숨겨지고 관리자 검토 대기가 됩니다.

## 5. 관리자 화면 (시스템 ADMIN)

```http
GET  /api/v1/admin/community/reports?status=OPEN&target_type=POST
POST /api/v1/admin/community/reports/{id}/resolve      { "action": "HIDE" | "NONE", "note": "…" }
POST /api/v1/admin/community/reports/{id}/dismiss      { "note": "…", "restore": true }
POST /api/v1/admin/community/posts/{id}/hide|unhide    { "reason": "…" }
POST /api/v1/admin/community/comments/{id}/hide|unhide { "reason": "…" }
GET  /api/v1/admin/community/moderation-logs
```

```json
// AdminReportRead
{ "id": "rp1…", "target_type": "POST", "post_id": "p1…", "comment_id": null,
  "reason": "SPAM", "detail": "광고", "status": "OPEN", "reporter_id": "u…",
  "target_status": "HIDDEN", "target_preview": "게시물 제목", "open_report_count": 3,
  "created_at": "…", "handled_at": null, "resolution_note": null }
```

- 처리·기각하면 같은 대상의 다른 미처리 신고도 함께 처리됩니다. 기각 시 `restore: true`면 자동 숨김된 대상을 복구합니다.
- 이력(`moderation-logs`)의 `actor_name: null`은 시스템 자동 숨김입니다.

## 6. 오류 코드

| HTTP | code | 상황 | 처리 |
| --- | --- | --- | --- |
| 409 | `FINAL_PHOTO_REQUIRED` | FINAL 대표 사진 없이 공유·우수 사례 확인 | 완성 사진 업로드 |
| 422 | `SHARING_SCOPE_INVALID` | 학원 미연결 작품의 ACADEMY 공유, 학원 탈퇴 | PLATFORM 선택 |
| 409 | `SHARING_CONSENT_REQUIRED` | 동의 없이 게시 | 공유 동의 화면 |
| 409 | `POST_ALREADY_EXISTS` | 작품당 게시물 1개 | 기존 게시물로 이동 |
| 409 | `ALREADY_REPORTED` | 중복 신고 | "이미 신고했어요" |
| 422 | `CANNOT_REPORT_OWN_CONTENT` | 본인 글 신고 | 버튼 숨김 |
| 409 | `REFERENCE_REVIEW_EXISTS` | 같은 작품·카테고리 중복 확인 | 목록 새로고침 |
| 409 | `REPORT_ALREADY_HANDLED` | 이미 처리된 신고 | 목록 새로고침 |
| 429 | `RATE_LIMITED` | 게시 하루 10개, 댓글 10분 20개, 신고 하루 20개 초과 (`details.retry_after_seconds`, `Retry-After`) | 잠시 후 |
| 503 | `STORAGE_UNAVAILABLE` / `STORAGE_NOT_CONFIGURED` | 공유 이미지 생성 실패 | 재시도 |
| 404 | `NOT_FOUND` | 볼 수 없는 게시물·추천(철회·숨김·범위 밖) | "찾을 수 없음" |
| 403 | `FORBIDDEN` | 남의 게시물·댓글 수정, 비담당 학생 작품 확인 | 버튼 숨김 |

`api()`는 `body` 객체를 그대로 넘깁니다.

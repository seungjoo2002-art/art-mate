import { api } from '../../lib/api'

// v0.8 커뮤니티 + v0.9 F-6 (docs/frontend-integration-v0.8.md §1·§4, v0.9.md §8)
// 게시물은 항상 내 작품 1개와 연결 (완성 사진 + 커뮤니티 공유 동의 필요, 작품당 1개)

/** category: PRACTICE_QUESTION | FEEDBACK_REQUEST | ARTWORK_SHARE | FREE (없으면 전체) */
/** q: 제목·본문·질문 부분 일치 (2~50자, 밖이면 서버 422라 보내지 않음) */
export const listFeed = ({ limit = 30, offset = 0, category, q } = {}) => {
  const params = new URLSearchParams({ limit, offset })
  if (category) params.set('category', category)
  if (q && q.length >= 2) params.set('q', q.slice(0, 50))
  return api(`/community/posts?${params}`)
}

/** 내 게시물 (숨김 포함, 최신순) */
export const listMyPosts = ({ limit = 50, offset = 0 } = {}) =>
  api(`/community/posts/me?limit=${limit}&offset=${offset}`)

export const getPost = (postId) => api(`/community/posts/${postId}`)

/**
 * 게시물 작성 (VER.2 P0)
 * - 작품 없이: body 필수, ARTWORK_SHARE 불가, authorDisplay(NAME | ANONYMOUS)
 * - 작품 게시물: 공유 동의 필요, photoId = 공유할 사진(스케치·중간·완성 중 1장, 생략 = 완성 대표 사진)
 */
export const createPost = ({
  category,
  artworkId,
  photoId,
  title,
  body,
  question,
  authorDisplay,
}) =>
  api('/community/posts', {
    method: 'POST',
    body: {
      category,
      title,
      body: body || null,
      question: question || null,
      ...(artworkId
        ? { artwork_id: artworkId, ...(photoId ? { photo_id: photoId } : {}) }
        : { author_display: authorDisplay }),
    },
  })

/** 게시물 수정 (VER.2): title·body·question·category, 작품 게시물은 photo_id, 사진 없는 글은 author_display */
export const updatePost = (postId, patch) =>
  api(`/community/posts/${postId}`, { method: 'PATCH', body: patch })

export const deletePost = (postId) => api(`/community/posts/${postId}`, { method: 'DELETE' })

/**
 * 커뮤니티 공유 철회: 게시물 삭제 + 공유 동의 철회 + 공유 이미지 삭제(참고작 동의가 없으면)
 * 내 게시물 "삭제"는 이걸로 처리 → 동의서의 "철회하면 바로 내려가요"와 맞춤
 */
export const revokeCommunitySharing = (artworkId) =>
  api(`/artworks/${artworkId}/sharing/COMMUNITY`, { method: 'DELETE' })

export const setLiked = (postId, liked) =>
  api(`/community/posts/${postId}/like`, { method: liked ? 'PUT' : 'DELETE' })

export const listComments = (postId) => api(`/community/posts/${postId}/comments?limit=100`)

/** commentType: GENERAL(일반 의견) | FEEDBACK(작품 피드백, categories 선택 가능) */
export const addComment = (postId, { body, commentType, categories, isAnonymous = false }) =>
  api(`/community/posts/${postId}/comments`, {
    method: 'POST',
    body: {
      body,
      is_anonymous: isAnonymous,
      comment_type: commentType,
      ...(commentType === 'FEEDBACK' ? { categories } : {}),
    },
  })

/** 댓글 수정 (본인만): 내용, 익명 여부 */
export const updateComment = (commentId, { body, isAnonymous }) =>
  api(`/community/comments/${commentId}`, {
    method: 'PATCH',
    body: { body, ...(isAnonymous === undefined ? {} : { is_anonymous: isAnonymous }) },
  })

export const deleteComment = (commentId) =>
  api(`/community/comments/${commentId}`, { method: 'DELETE' })

/** 작품 피드백 댓글 채택 → 내 작품의 글 첨삭(출처 PEER)으로 저장 (게시물 작성자) */
export const adoptComment = (commentId) =>
  api(`/community/comments/${commentId}/adopt`, {
    method: 'POST',
    body: { request_summary: false },
  })

/** reason: SPAM | ABUSE | INAPPROPRIATE | COPYRIGHT | PRIVACY | OTHER */
export const reportPost = (postId, reason) =>
  api(`/community/posts/${postId}/reports`, { method: 'POST', body: { reason } })
export const reportComment = (commentId, reason) =>
  api(`/community/comments/${commentId}/reports`, { method: 'POST', body: { reason } })

export const getSharing = (artworkId) => api(`/artworks/${artworkId}/sharing`)

/** 커뮤니티 게시 동의. authorDisplay: NAME(내 닉네임) | ANONYMOUS('익명 학생') */
export const grantCommunitySharing = (artworkId, { authorDisplay, policyVersion, grantedBy }) =>
  api(`/artworks/${artworkId}/sharing/COMMUNITY`, {
    method: 'PUT',
    body: {
      scope: 'PLATFORM', // 학생 전용 서비스: ART MATE 사용자 전체
      author_display: authorDisplay,
      policy_version: policyVersion,
      agreed: true,
      granted_by: grantedBy,
    },
  })

import { api } from '../../lib/api'

// v0.8 커뮤니티 + v0.9 F-6 (docs/frontend-integration-v0.8.md §1·§4, v0.9.md §8)
// 게시물은 항상 내 작품 1개와 연결 (완성 사진 + 커뮤니티 공유 동의 필요, 작품당 1개)

export const listFeed = ({ limit = 30, offset = 0 } = {}) =>
  api(`/community/posts?limit=${limit}&offset=${offset}`)

/** 내 게시물 (숨김 포함, 최신순) */
export const listMyPosts = ({ limit = 50, offset = 0 } = {}) =>
  api(`/community/posts/me?limit=${limit}&offset=${offset}`)

export const getPost = (postId) => api(`/community/posts/${postId}`)

/** question이 있으면 "피드백 요청" 글 */
export const createPost = ({ artworkId, title, body, question }) =>
  api('/community/posts', {
    method: 'POST',
    body: { artwork_id: artworkId, title, body: body || null, question: question || null },
  })

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
export const addComment = (postId, { body, commentType, categories }) =>
  api(`/community/posts/${postId}/comments`, {
    method: 'POST',
    body: {
      body,
      comment_type: commentType,
      ...(commentType === 'FEEDBACK' ? { categories } : {}),
    },
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

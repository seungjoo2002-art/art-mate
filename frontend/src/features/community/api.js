import { api } from '../../lib/api'

// v0.8 커뮤니티 (docs/frontend-integration-v0.8.md §4)

/** 내 게시물 (숨김 포함, 최신순) */
export const listMyPosts = ({ limit = 50, offset = 0 } = {}) =>
  api(`/community/posts/me?limit=${limit}&offset=${offset}`)

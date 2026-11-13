// 게시판 분류 (VER.2 P0, 서버의 post.category)
export const CATEGORIES = [
  { code: 'PRACTICE_QUESTION', label: '실기 질문' },
  { code: 'FEEDBACK_REQUEST', label: '피드백 요청' },
  { code: 'ARTWORK_SHARE', label: '작품 공유' }, // 작품(사진) 필수
  { code: 'FREE', label: '자유게시판' },
]

export const postCategory = (post) =>
  CATEGORIES.find((c) => c.code === post.category)?.label ?? '게시물'

/** 목록 칩: 전체 + 분류 4개 (서버 category 필터) */
export const CATEGORY_FILTERS = [{ code: 'all', label: '전체' }, ...CATEGORIES]

export const REPORT_REASONS = [
  { code: 'SPAM', label: '스팸·광고' },
  { code: 'ABUSE', label: '욕설·괴롭힘' },
  { code: 'INAPPROPRIATE', label: '부적절한 내용' },
  { code: 'COPYRIGHT', label: '작품 도용' },
  { code: 'PRIVACY', label: '개인정보 노출' },
  { code: 'OTHER', label: '기타' },
]

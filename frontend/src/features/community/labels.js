// 백엔드에는 게시판 분류가 없어서, 작품 질문(question)이 있으면 "피드백 요청", 없으면 "작품 공유"로 표시
export const postCategory = (post) => (post.question ? '피드백 요청' : '작품 공유')

export const CATEGORY_FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'feedback', label: '피드백 요청' },
  { key: 'share', label: '작품 공유' },
]

export const matchesCategory = (post, key) =>
  key === 'all' || (key === 'feedback' ? Boolean(post.question) : !post.question)

export const REPORT_REASONS = [
  { code: 'SPAM', label: '스팸·광고' },
  { code: 'ABUSE', label: '욕설·괴롭힘' },
  { code: 'INAPPROPRIATE', label: '부적절한 내용' },
  { code: 'COPYRIGHT', label: '작품 도용' },
  { code: 'PRIVACY', label: '개인정보 노출' },
  { code: 'OTHER', label: '기타' },
]

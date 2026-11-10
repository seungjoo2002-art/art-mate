// 문구 규칙 (백엔드 문서): 언급이 줄었거나 안 나온 것을 "개선됨"이라고 쓰지 않음. AI 채점이 아님

export const TREND_LABELS = {
  MORE_FREQUENT: '최근 첨삭에서 더 자주 언급됨',
  LESS_FREQUENT: '최근 첨삭에서 덜 언급됨',
  SIMILAR: '최근에도 비슷하게 언급됨',
  INSUFFICIENT_DATA: '비교할 기록이 부족해요',
}

export const PERIOD_LABELS = {
  WEEK: '최근 7일',
  MONTH: '최근 30일',
  ALL: '전체 기간',
  CUSTOM: '직접 지정',
}

export const DIFFICULTY_LABELS = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' }

export const RECOMMENDATION_STATUS = {
  DRAFT: '새 추천',
  IN_REVIEW: '새 추천',
  ADOPTED: '진행 중',
  COMPLETED: '완료',
  REJECTED: '거절함',
  SUPERSEDED: '대체됨',
  APPROVED: '승인됨',
  DISTRIBUTED: '학원 과제',
}

export const FOLLOW_UP_LABELS = {
  NO_LINKED_ARTWORK: '아직 이 과제로 그린 작품이 없어요.',
  NO_FOLLOW_UP_FEEDBACK: '연결된 작품에 확정된 첨삭이 아직 없어요.',
  REAPPEARED: '후속 첨삭에서 이 약점이 다시 지적됐어요.',
  NOT_MENTIONED: '후속 첨삭에서 이 약점은 언급되지 않았어요.',
}

export const INSUFFICIENT_REASONS = {
  NOT_ENOUGH_ARTWORKS: '확정된 첨삭이 있는 작품이 더 필요해요.',
  NO_REPEATED_WEAKNESS: '아직 여러 작품에서 반복된 약점이 없어요.',
}

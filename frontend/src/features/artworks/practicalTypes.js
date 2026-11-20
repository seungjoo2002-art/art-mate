/** 실기 유형 물감 색 (칩의 물감 점, 아카이브 스케치북 클립). 코드에 없는 유형은 주황 */
export const PRACTICAL_TYPE_COLORS = {
  BASIC_DESIGN: '#f2933a',
  THINKING_SHIFT: '#7c6ee6',
  IDEA_EXPRESSION: '#e0607e',
  DRAWING: '#555555',
  WATERCOLOR: '#3fa7d6',
  OTHER: '#9aa33f',
}

export const typeColor = (code) => PRACTICAL_TYPE_COLORS[code] ?? 'var(--color-primary)'

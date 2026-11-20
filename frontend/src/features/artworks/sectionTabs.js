/**
 * 새 작품 기록의 스케치북 인덱스 탭 색 (1~6번 칸 순서).
 * 실기 유형 물감 색을 연하게 한 것 → 탭 위 검정 글자 대비 7:1 이상
 */
export const SECTION_TAB_COLORS = ['#f2933a', '#a99ff0', '#f29bb0', '#86c9e8', '#c3cc72', '#e9b949']

export const tabColor = (number) =>
  SECTION_TAB_COLORS[(number - 1) % SECTION_TAB_COLORS.length]

/** "01 · 무엇을 그리나요" */
export const tabLabel = (number, title) => `${String(number).padStart(2, '0')} · ${title}`

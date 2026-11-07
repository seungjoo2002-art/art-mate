/** 예: "5월 22일 목요일" */
export function formatToday(date = new Date()) {
  return new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' }).format(
    date,
  )
}

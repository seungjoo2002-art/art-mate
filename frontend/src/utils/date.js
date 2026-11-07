/** 예: "5월 22일 목요일" */
export function formatToday(date = new Date()) {
  return new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' }).format(
    date,
  )
}

const pad = (n) => String(n).padStart(2, '0')

/** "2026-05-21" → "5월 21일" (날짜만 있는 값은 시간대 영향 없이 그대로) */
export function formatMonthDay(isoDate) {
  const [, month, day] = isoDate.split('-').map(Number)
  return `${month}월 ${day}일`
}

/** 업로드 시각: 오늘이면 "오늘 14:32", 아니면 "5월 21일 14:32" */
export function formatUploadedAt(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const isToday = date.toDateString() === new Date().toDateString()
  return isToday ? `오늘 ${time}` : `${date.getMonth() + 1}월 ${date.getDate()}일 ${time}`
}

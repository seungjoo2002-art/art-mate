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

/** 게시판 목록 시각: "방금 전", "10분 전", "3시간 전", "2일 전", 일주일이 넘으면 "5월 21일" */
export function formatTimeAgo(iso, now = new Date()) {
  if (!iso) return ''
  const date = new Date(iso)
  const minutes = Math.floor((now - date) / 60000)
  if (minutes < 1) return '방금 전'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}일 전`
  const sameYear = date.getFullYear() === now.getFullYear()
  return `${sameYear ? '' : `${date.getFullYear()}년 `}${date.getMonth() + 1}월 ${date.getDate()}일`
}

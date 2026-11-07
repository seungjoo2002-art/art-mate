const pad = (n) => String(n).padStart(2, '0')

/** 95400 → "01:35" */
export function formatDuration(ms) {
  const total = Math.floor(ms / 1000)
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`
}

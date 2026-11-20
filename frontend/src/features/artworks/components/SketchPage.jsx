import { Link } from 'react-router-dom'
import styles from './SketchPage.module.css'

/** id → 0~1 사이 고정 난수 (카드마다 찢긴 모양·기울기가 다르지만 새로고침해도 같게) */
function seeded(id, salt) {
  let h = 2166136261 ^ salt
  for (const ch of String(id)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619)
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507)
    h = Math.imul(h ^ (h >>> 13), 3266489909)
    return ((h ^= h >>> 16) >>> 0) / 4294967296
  }
}

/** 찢긴 윗변: 폭 따라 높이가 들쭉날쭉한 다각형 */
function tornEdge(id) {
  const rand = seeded(id, 7)
  const points = []
  for (let x = 0; x < 100; x += 2.5 + rand() * 2.5) {
    points.push(`${x.toFixed(1)}% ${(rand() * 7).toFixed(1)}px`)
  }
  return `polygon(${points.join(',')},100% 3px,100% 100%,0 100%)`
}

/**
 * 스케치북에서 뜯어낸 한 장 (종이결 · 찢긴 윗변 · 스프링 구멍). 아카이브 전체 기록·공개 피드 공용
 * fastener: clip(내 기록, 클립) | pin(공개, 게시판 압정). accent = 클립·압정 색 (실기 유형 색)
 * media: 사진 자리 (className은 photoClass), footer: 제목 아래 줄
 */
export default function SketchPage({ to, seed, accent, fastener = 'clip', media, date, title, footer }) {
  const tilt = (seeded(seed, 3)() - 0.5) * 3 // -1.5° ~ 1.5°

  return (
    <Link
      to={to}
      className={styles.card}
      style={{ rotate: `${tilt.toFixed(2)}deg`, '--accent': accent }}
    >
      {fastener === 'pin' ? (
        <i className={styles.pin} aria-hidden />
      ) : (
        <svg className={styles.clip} viewBox="0 0 16 40" aria-hidden focusable="false">
          <path d="M5 30V8a4 4 0 0 1 8 0v26a6 6 0 0 1-12 0V12" />
        </svg>
      )}
      <span className={styles.paper} style={{ clipPath: tornEdge(seed) }}>
        <span className={styles.holes} aria-hidden>
          {Array.from({ length: 8 }, (_, i) => (
            <i key={i} />
          ))}
        </span>
        {media}
        <span className={styles.date}>{date}</span>
        <strong className={styles.title}>{title}</strong>
        {footer}
      </span>
    </Link>
  )
}

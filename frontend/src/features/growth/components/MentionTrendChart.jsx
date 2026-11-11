import { useState } from 'react'
import styles from './MentionTrendChart.module.css'

// 두 계열 색 (dataviz 검증 통과: CVD ΔE 22.3, 주황은 배경 대비 2.97 → 값 라벨 + 표 보기로 보완)
const SERIES = [
  { key: 'positive', label: '긍정 언급', color: '#3b82c4' },
  { key: 'improve', label: '개선 요청', color: '#e0782a' },
]
const W = 320
const H = 170
const PAD = { top: 20, right: 28, bottom: 26, left: 24 }

/**
 * 작품별 긍정 언급 / 개선 요청 횟수 선 그래프 (작업 날짜순)
 * points: [{ label: '10/4', title: '작품명', positive: 2, improve: 1 }]
 */
export default function MentionTrendChart({ points }) {
  const [active, setActive] = useState(null)
  const max = Math.max(1, ...points.flatMap((p) => [p.positive, p.improve]))
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const x = (i) =>
    PAD.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW)
  const y = (v) => PAD.top + innerH - (v / max) * innerH
  const ticks = [...new Set([0, Math.ceil(max / 2), max])]
  const last = points.length - 1

  function handleMove(e) {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    let nearest = 0
    points.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(nearest) - px)) nearest = i
    })
    setActive(nearest)
  }

  return (
    <figure className={styles.figure}>
      <div className={styles.legend}>
        {SERIES.map((s) => (
          <span key={s.key} className={styles.legendItem}>
            <span className={styles.swatch} style={{ background: s.color }} aria-hidden />
            {s.label}
          </span>
        ))}
      </div>

      <div className={styles.plot}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className={styles.svg}
          role="img"
          aria-label="작품별 긍정 언급과 개선 요청 횟수"
          onPointerMove={handleMove}
          onPointerLeave={() => setActive(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={styles.grid} />
              <text
                x={PAD.left - 6}
                y={y(t)}
                className={styles.axis}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {t}
              </text>
            </g>
          ))}
          {points.map((p, i) => (
            <text key={i} x={x(i)} y={H - 6} className={styles.axis} textAnchor="middle">
              {p.label}
            </text>
          ))}

          {active !== null && (
            <line
              x1={x(active)}
              x2={x(active)}
              y1={PAD.top - 6}
              y2={PAD.top + innerH}
              className={styles.crosshair}
            />
          )}

          {SERIES.map((s) => (
            <g key={s.key}>
              <polyline
                points={points.map((p, i) => `${x(i)},${y(p[s.key])}`).join(' ')}
                fill="none"
                stroke={s.color}
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {points.map((p, i) => (
                <circle
                  key={i}
                  cx={x(i)}
                  cy={y(p[s.key])}
                  r={active === i ? 5 : 4}
                  fill={s.color}
                  stroke="var(--color-surface)"
                  strokeWidth="2"
                />
              ))}
              {/* 마지막 값만 직접 라벨 */}
              <text
                x={x(last) + 8}
                y={y(points[last][s.key])}
                className={styles.value}
                dominantBaseline="middle"
              >
                {points[last][s.key]}
              </text>
            </g>
          ))}

          {/* 키보드: 날짜마다 초점 받는 칸 */}
          {points.map((p, i) => (
            <rect
              key={i}
              x={x(i) - innerW / Math.max(1, points.length) / 2}
              y={PAD.top}
              width={innerW / Math.max(1, points.length)}
              height={innerH}
              fill="transparent"
              tabIndex={0}
              aria-label={`${p.label} ${p.title}: 긍정 ${p.positive}, 개선 ${p.improve}`}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            />
          ))}
        </svg>

        {active !== null && (
          <div
            className={styles.tooltip}
            style={{ left: `${Math.min(78, Math.max(22, (x(active) / W) * 100))}%` }}
            role="status"
          >
            <strong>{points[active].title}</strong>
            <span>{points[active].label}</span>
            {SERIES.map((s) => (
              <span key={s.key} className={styles.tooltipRow}>
                <span className={styles.swatch} style={{ background: s.color }} aria-hidden />
                {s.label} {points[active][s.key]}회
              </span>
            ))}
          </div>
        )}
      </div>

      <details className={styles.table}>
        <summary>표로 보기</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">작품</th>
              <th scope="col">날짜</th>
              {SERIES.map((s) => (
                <th key={s.key} scope="col">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={i}>
                <td>{p.title}</td>
                <td>{p.label}</td>
                <td>{p.positive}</td>
                <td>{p.improve}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}

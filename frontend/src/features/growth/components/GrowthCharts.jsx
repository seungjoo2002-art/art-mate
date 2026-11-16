import { mentionBars, periodCounts } from '../growthView'
import styles from './GrowthCharts.module.css'

/** v1.0 항목별(9개 태그) 강점·약점 언급 작품 수 — 가로 막대 (모바일 우선) */
export function TagMentionBars({ analysis }) {
  const { rows, max } = mentionBars(analysis)
  if (!rows.length) return null
  return (
    <div className={styles.chart}>
      <div className={styles.legend} aria-hidden>
        <span className={styles.legendWeak}>개선할 점</span>
        <span className={styles.legendStrong}>잘한 점</span>
      </div>
      <ul className={styles.bars} aria-label="항목별 강점·약점 언급">
        {rows.map((r) => (
          <li key={r.key} className={styles.barRow}>
            <span className={styles.barLabel}>{r.label}</span>
            <span className={styles.barTrack}>
              <span
                className={styles.barWeak}
                style={{ width: `${(r.weak / max) * 100}%` }}
                aria-hidden
              />
              <span
                className={styles.barStrong}
                style={{ width: `${(r.strong / max) * 100}%` }}
                aria-hidden
              />
            </span>
            <span className={styles.barValue}>
              <span className={styles.srOnly}>개선할 점 </span>
              {r.weak}
              <span className={styles.sep}>/</span>
              <span className={styles.srOnly}>잘한 점 </span>
              {r.strong}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** v1.0 기간별 첨삭 횟수 — 세로 막대 */
export function PeriodFeedbackBars({ analysis }) {
  const points = periodCounts(analysis).slice(-6)
  if (!points.length) return null
  const max = Math.max(1, ...points.map((p) => p.count))
  return (
    <ol className={styles.columns} aria-label="기간별 첨삭 횟수">
      {points.map((p) => (
        <li key={p.key} className={styles.column}>
          <span className={styles.columnValue}>{p.count}</span>
          <span className={styles.columnTrack}>
            <span className={styles.columnFill} style={{ height: `${(p.count / max) * 100}%` }} />
          </span>
          <span className={styles.columnLabel}>{p.label}</span>
        </li>
      ))}
    </ol>
  )
}

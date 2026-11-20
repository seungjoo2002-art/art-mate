import { typeColor } from '../practicalTypes'
import styles from './PaintChips.module.css'

/**
 * 실기 유형 물감 점 칩 (하나 고르기). options: [{ code, label }], code ''면 점 없는 "전체" 같은 칩
 * toggleable: 고른 칩을 다시 누르면 선택 해제 (새 작품 기록). wrap=false면 한 줄 가로 스크롤 (아카이브)
 */
export default function PaintChips({ options, value, onChange, label, toggleable = false, wrap = true }) {
  return (
    <div
      className={`${styles.chips} ${wrap ? '' : styles.scroll}`}
      role="radiogroup"
      aria-label={label}
    >
      {options.map((o) => (
        <button
          key={o.code || 'all'}
          type="button"
          role="radio"
          aria-checked={value === o.code}
          className={styles.chip}
          style={o.code ? { '--paint': typeColor(o.code) } : undefined}
          onClick={() => onChange(toggleable && value === o.code ? '' : o.code)}
        >
          {o.code && <i className={styles.paint} aria-hidden />}
          {o.label}
        </button>
      ))}
    </div>
  )
}

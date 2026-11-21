import { typeColor } from '../practicalTypes'
import styles from './PaintChips.module.css'

/**
 * 실기 유형 물감 점 칩 (하나 고르기). options: [{ code, label }], code ''면 점 없는 "전체" 같은 칩
 * toggleable: 고른 칩을 다시 누르면 선택 해제 (새 작품 기록). wrap=false면 한 줄 가로 스크롤 (아카이브)
 * colorOf: 코드 → 점 색 (기본 실기 유형 색). null을 주면 점 없음
 */
export default function PaintChips({
  options,
  value,
  onChange,
  label,
  toggleable = false,
  wrap = true,
  colorOf = (code) => (code ? typeColor(code) : null),
}) {
  return (
    <div
      className={`${styles.chips} ${wrap ? '' : styles.scroll}`}
      role="radiogroup"
      aria-label={label}
    >
      {options.map((o) => {
        const color = colorOf(o.code)
        return (
          <button
            key={o.code || 'all'}
            type="button"
            role="radio"
            aria-checked={value === o.code}
            className={styles.chip}
            style={color ? { '--paint': color } : undefined}
            onClick={() => onChange(toggleable && value === o.code ? '' : o.code)}
          >
            {color && <i className={styles.paint} aria-hidden />}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

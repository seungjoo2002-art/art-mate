import styles from './Chip.module.css'

/** 필터용 알약 버튼 (전체 / 기초디자인 / 모의시험 …) */
export default function Chip({ selected = false, className = '', ...props }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={`${styles.chip} ${selected ? styles.selected : ''} ${className}`}
      {...props}
    />
  )
}

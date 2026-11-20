import styles from './SegmentedTabs.module.css'

/**
 * 탭. tabs: [{ key, label }]
 * variant: segmented(회색 바탕 위 흰색 선택, 기본) | highlight(글자만, 고른 탭에 주황 붓 형광펜)
 */
export default function SegmentedTabs({ tabs, value, onChange, label, variant = 'segmented' }) {
  return (
    <div
      className={`${styles.tabs} ${variant === 'highlight' ? styles.highlight : ''}`}
      role="tablist"
      aria-label={label}
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={value === tab.key}
          className={`${styles.tab} ${value === tab.key ? styles.active : ''}`}
          onClick={() => onChange(tab.key)}
        >
          <span className={styles.label}>{tab.label}</span>
        </button>
      ))}
    </div>
  )
}

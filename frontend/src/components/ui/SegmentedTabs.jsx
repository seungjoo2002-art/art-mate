import styles from './SegmentedTabs.module.css'

/** 회색 바탕 위 흰색 선택 탭. tabs: [{ key, label }] */
export default function SegmentedTabs({ tabs, value, onChange, label }) {
  return (
    <div className={styles.tabs} role="tablist" aria-label={label}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={value === tab.key}
          className={`${styles.tab} ${value === tab.key ? styles.active : ''}`}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

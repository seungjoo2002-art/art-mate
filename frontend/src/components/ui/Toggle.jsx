import styles from './Toggle.module.css'

export default function Toggle({ checked, onChange, label, ...props }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`${styles.track} ${checked ? styles.on : ''}`}
      onClick={() => onChange?.(!checked)}
      {...props}
    >
      <span className={styles.thumb} />
    </button>
  )
}

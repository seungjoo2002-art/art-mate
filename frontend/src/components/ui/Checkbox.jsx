import { Check } from 'lucide-react'
import styles from './Checkbox.module.css'

export default function Checkbox({ checked, onChange, children, className = '', ...props }) {
  return (
    <label className={`${styles.wrap} ${className}`}>
      <input
        type="checkbox"
        className={styles.native}
        checked={checked}
        onChange={(e) => onChange?.(e.target.checked)}
        {...props}
      />
      <span className={styles.box} aria-hidden>
        <Check size={18} strokeWidth={3} />
      </span>
      {children && <span className={styles.text}>{children}</span>}
    </label>
  )
}

import { useId } from 'react'
import { ChevronDown } from 'lucide-react'
import styles from './Select.module.css'

/** 드롭다운. options: [{ code, label }]. placeholder가 있으면 빈 값('')을 첫 항목으로 */
export default function Select({ label, options = [], placeholder, id, className = '', ...props }) {
  const autoId = useId()
  const selectId = id ?? autoId

  return (
    <div className={`${styles.field} ${className}`}>
      {label && (
        <label htmlFor={selectId} className={styles.label}>
          {label}
        </label>
      )}
      <div className={styles.box}>
        <select id={selectId} className={styles.select} {...props}>
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown size={20} className={styles.icon} aria-hidden />
      </div>
    </div>
  )
}

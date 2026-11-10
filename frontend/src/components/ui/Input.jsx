import { useId } from 'react'
import styles from './Input.module.css'

/** 라벨 + 왼쪽 아이콘이 있는 입력창. icon에는 lucide 아이콘 컴포넌트를 넘김 */
export default function Input({ label, icon: Icon, error, id, className = '', ...props }) {
  const autoId = useId()
  const inputId = id ?? autoId

  return (
    <div className={`${styles.field} ${className}`}>
      {label && (
        <label htmlFor={inputId} className={styles.label}>
          {label}
        </label>
      )}
      <div className={`${styles.box} ${error ? styles.invalid : ''}`}>
        {Icon && <Icon size={22} className={styles.icon} aria-hidden />}
        <input
          id={inputId}
          className={styles.input}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${inputId}-error` : undefined}
          {...props}
        />
      </div>
      {error && (
        <p id={`${inputId}-error`} className={styles.error}>
          {error}
        </p>
      )}
    </div>
  )
}

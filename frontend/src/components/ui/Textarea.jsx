import { useId } from 'react'
import styles from './Textarea.module.css'

/** 여러 줄 입력칸. label이 없으면 aria-label을 넘길 것 */
export default function Textarea({ label, id, className = '', ...props }) {
  const autoId = useId()
  const inputId = id ?? autoId

  return (
    <div className={`${styles.field} ${className}`}>
      {label && (
        <label htmlFor={inputId} className={styles.label}>
          {label}
        </label>
      )}
      <textarea id={inputId} className={styles.textarea} rows={3} {...props} />
    </div>
  )
}

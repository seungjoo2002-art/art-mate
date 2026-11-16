import styles from './Instructor.module.css'

const TONE = { todo: styles.statusTodo, done: styles.statusDone, danger: styles.statusDanger }

/** 상태 표시: status는 FEEDBACK_STATUS 등의 { label, tone } */
export default function StatusBadge({ status, fallback }) {
  return <span className={TONE[status?.tone] ?? styles.status}>{status?.label ?? fallback}</span>
}

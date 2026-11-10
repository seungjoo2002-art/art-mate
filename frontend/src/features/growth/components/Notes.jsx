import { Info } from 'lucide-react'
import styles from './Notes.module.css'

/** 분석 응답의 notes (AI 채점 아님 등). 백엔드 문서상 항상 함께 보여 줘야 함 */
export default function Notes({ notes }) {
  if (!notes?.length) return null
  return (
    <ul className={styles.notes}>
      {notes.map((note) => (
        <li key={note}>
          <Info size={14} aria-hidden />
          <span>{note}</span>
        </li>
      ))}
    </ul>
  )
}

import { ChevronDown, Info } from 'lucide-react'
import styles from './Notes.module.css'

/**
 * 분석 응답의 notes (AI 채점 아님 등). 백엔드 문서상 항상 함께 보여 줘야 함.
 * 길어서 한 줄 요약은 늘 보이게 두고, 원문 전체는 '자세히'를 누르면 펼침 (지우지 않음)
 */
export default function Notes({ notes }) {
  if (!notes?.length) return null
  return (
    <details className={styles.notes}>
      <summary>
        <Info size={13} aria-hidden />
        <span>선생님 첨삭을 모아 정리한 거예요. AI가 채점한 결과가 아니에요.</span>
        <span className={styles.more}>
          자세히 <ChevronDown size={12} aria-hidden />
        </span>
      </summary>
      <ul>
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </details>
  )
}

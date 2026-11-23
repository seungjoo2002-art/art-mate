import { Link } from 'react-router-dom'
import { formatMonthDay } from '../../../utils/date'
import styles from './EvidenceList.module.css'

/**
 * 실제 첨삭 근거 문장 + 작품 링크
 * withSource(v1.2): 정리 문장 아래에 첨삭 원문(전사 구간·텍스트 첨삭 문장)을 펼쳐 볼 수 있게
 */
export default function EvidenceList({ evidence, limit = 3, withSource = false }) {
  if (!evidence?.length) return null
  return (
    <ul className={styles.list}>
      {evidence.slice(0, limit).map((item) => (
        <li key={item.item_id}>
          <p className={styles.content}>“{item.content}”</p>
          {withSource && item.source_text?.length > 0 && (
            <details className={styles.original}>
              <summary>첨삭 원문 보기</summary>
              <p>{item.source_text.join(' ')}</p>
              <Link to={`/feedbacks/${item.feedback_id}`} className={styles.source}>
                정리 결과 전체 보기
              </Link>
            </details>
          )}
          <Link to={`/artworks/${item.artwork_id}`} className={styles.source}>
            {item.artwork_title}
            {item.work_date && ` · ${formatMonthDay(item.work_date)}`}
          </Link>
        </li>
      ))}
    </ul>
  )
}

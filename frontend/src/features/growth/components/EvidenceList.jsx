import { Link } from 'react-router-dom'
import { formatMonthDay } from '../../../utils/date'
import styles from './EvidenceList.module.css'

/** 실제 첨삭 근거 문장 + 작품 링크 */
export default function EvidenceList({ evidence, limit = 3 }) {
  if (!evidence?.length) return null
  return (
    <ul className={styles.list}>
      {evidence.slice(0, limit).map((item) => (
        <li key={item.item_id}>
          <p className={styles.content}>“{item.content}”</p>
          <Link to={`/artworks/${item.artwork_id}`} className={styles.source}>
            {item.artwork_title}
            {item.work_date && ` · ${formatMonthDay(item.work_date)}`}
          </Link>
        </li>
      ))}
    </ul>
  )
}

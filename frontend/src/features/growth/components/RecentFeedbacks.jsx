import { useCallback } from 'react'
import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getGrowthSummary } from '../api'
import styles from './GrowthOverview.module.css'

/** 아카이브 "첨삭" 탭: 최근 확정한 첨삭 */
export default function RecentFeedbacks() {
  const options = useOptions()
  const load = useCallback(() => getGrowthSummary(), [])
  const { data, error } = useAsync(load)

  if (error) return <Card variant="soft">{toErrorMessage(error)}</Card>
  if (!data) return null
  if (!data.recent_feedbacks.length) {
    return (
      <Card variant="soft">아직 확정한 첨삭이 없어요. 녹음을 AI로 정리하고 확정해 보세요.</Card>
    )
  }

  return (
    <ul className={styles.wrap}>
      {data.recent_feedbacks.map((f) => (
        <li key={f.id}>
          <Card as={Link} to={`/feedbacks/${f.id}`} className={styles.link}>
            <span className={styles.feedbackText}>
              <span className={styles.feedbackTitle}>{f.artwork_title}</span>
              <span className={styles.feedbackSummary}>{f.summary}</span>
            </span>
            {f.categories.slice(0, 2).map((c) => (
              <Badge key={c}>{options ? labelOf(options.weakness_categories, c) : c}</Badge>
            ))}
            <ChevronRight size={18} aria-hidden />
          </Card>
        </li>
      ))}
    </ul>
  )
}

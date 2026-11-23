import { useCallback, useState } from 'react'
import { ChevronRight, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { usePolling } from '../../../hooks/usePolling'
import { toErrorMessage } from '../../../utils/errorMessages'
import tabStyles from '../../artworks/SectionTabs.module.css'
import { tabColor } from '../../artworks/sectionTabs'
import { getBriefing } from '../api'
import { aiCommentView, briefingNeedsPolling, briefingView } from '../insightsView'
import styles from './BriefingCard.module.css'

const POLL_MS = 30_000
const MAX_POLLS = 10 // 정리 중·코멘트 갱신 중일 때만, 최대 5분

/**
 * 홈 '오늘의 브리핑' (v1.2, GET /growth/me/briefing).
 * 조회만 한다: 서버가 확정된 첨삭으로 문장을 만들고, AI 코멘트는 저장된 것을 돌려준다.
 * userId가 바뀌면(계정 전환) 새로 불러와 이전 사용자 브리핑을 보여 주지 않는다.
 */
export default function BriefingCard({ userId }) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(() => getBriefing(), [userId])
  const { data, error, loading, reload } = useAsync(load)
  const [polls, setPolls] = useState(0)

  const poll = useCallback(() => {
    setPolls((n) => n + 1)
    reload()
  }, [reload])
  usePolling(Boolean(data) && briefingNeedsPolling(data) && polls < MAX_POLLS, POLL_MS, poll, [data])

  return (
    <section className={tabStyles.card} style={{ '--tab': tabColor(1) }} aria-busy={loading}>
      <h2 className={tabStyles.tab}>오늘의 브리핑</h2>
      {error ? (
        <BriefingError error={error} onRetry={reload} />
      ) : !data ? (
        <p className={styles.muted}>브리핑을 불러오는 중이에요…</p>
      ) : (
        <BriefingBody briefing={data} />
      )}
    </section>
  )
}

function BriefingBody({ briefing }) {
  const view = briefingView(briefing)
  const ai = aiCommentView(briefing.ai_comment)
  return (
    <>
      <small className={tabStyles.cardMeta}>{view.meta}</small>
      <p className={styles.title}>{view.title}</p>
      {view.lines.length > 0 && (
        <ul className={styles.lines}>
          {view.lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {ai && (
        <div className={styles.ai} aria-live="polite">
          <span className={styles.aiLabel}>
            <Sparkles size={14} aria-hidden /> {ai.label}
          </span>
          {ai.text && <p className={styles.aiText}>{ai.text}</p>}
          {ai.note && <p className={styles.aiNote}>{ai.note}</p>}
        </div>
      )}
      {view.cta && (
        <Link to={view.cta.to} className={styles.pill}>
          {view.cta.label} <ChevronRight size={16} aria-hidden />
        </Link>
      )}
    </>
  )
}

function BriefingError({ error, onRetry }) {
  return (
    <div className={styles.error}>
      <p className={styles.muted}>브리핑을 불러오지 못했어요. {toErrorMessage(error)}</p>
      <Button variant="soft" size="md" onClick={onRetry}>
        다시 시도
      </Button>
    </div>
  )
}

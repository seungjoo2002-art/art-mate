import { useCallback, useState } from 'react'
import { ChevronRight, Sparkles } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Badge, Button, Card, PageIntro } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { usePolling } from '../../../hooks/usePolling'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { generateRecommendations, getGrowthJob, listRecommendations } from '../api'
import { DIFFICULTY_LABELS, INSUFFICIENT_REASONS, RECOMMENDATION_STATUS } from '../labels'
import styles from './GrowthPage.module.css'

const HIDDEN = ['SUPERSEDED']
const ORDER = { ADOPTED: 0, DRAFT: 1, IN_REVIEW: 1, COMPLETED: 2, REJECTED: 3 }

/** 반복 약점 기반 맞춤 연습 과제 (개인) */
export default function RecommendationsPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const options = useOptions()
  const load = useCallback(() => listRecommendations(), [])
  const { data, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [job, setJob] = useState(null)

  // AI 생성 작업 폴링 → 끝나면 목록 다시 조회
  const pollJob = useCallback(async () => {
    try {
      const next = await getGrowthJob(job.id)
      setJob(next)
      if (next.status === 'SUCCEEDED') reload()
      if (next.status === 'FAILED')
        setMessage('AI가 과제를 만들지 못했어요. 기본 추천을 받아 보세요.')
      if (next.status === 'CANCELLED') setMessage('AI 성장 코칭 동의가 철회되어 취소됐어요.')
    } catch (err) {
      setMessage(toErrorMessage(err))
      setJob(null)
    }
  }, [job, reload])
  const jobActive = ['QUEUED', 'RUNNING'].includes(job?.status)
  usePolling(jobActive, 5000, pollJob, [job])

  async function generate(useAi) {
    setBusy(true)
    setMessage('')
    try {
      const result = await generateRecommendations({ useAi })
      if (result.status === 'QUEUED') setJob(result.job)
      else {
        if (result.status === 'EXISTING')
          setMessage('새로 분석할 기록이 없어 기존 추천을 보여 드려요.')
        reload()
      }
    } catch (err) {
      if (err.code === 'AI_CONSENT_REQUIRED') {
        navigate('/ai-consent?purpose=GROWTH_COACHING', { state: { from: location.pathname } })
        return
      }
      setMessage(
        err.code === 'INSUFFICIENT_DATA'
          ? (INSUFFICIENT_REASONS[err.details?.reason] ?? '기록이 더 쌓이면 추천해 드릴게요.')
          : err.code === 'GROWTH_AI_NOT_CONFIGURED'
            ? 'AI 추천은 아직 준비 중이에요. 기본 추천을 받아 보세요.'
            : toErrorMessage(err),
      )
    } finally {
      setBusy(false)
    }
  }

  const items = (data?.items ?? [])
    .filter((r) => !HIDDEN.includes(r.status))
    .sort((a, b) => (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9))

  return (
    <>
      <TopBar title="맞춤 연습 과제" belowHeader />
      <main className={styles.body}>
        <PageIntro
          eyebrow="PRACTICE"
          title="나에게 맞는 연습 과제"
          description="여러 작품에서 반복해서 지적된 약점을 연습할 과제를 추천해요."
        />

        <div className={styles.actions}>
          <Button onClick={() => generate(false)} disabled={busy || jobActive}>
            {busy ? '추천하는 중…' : '연습 과제 추천받기'}
          </Button>
          <Button variant="soft" onClick={() => generate(true)} disabled={busy || jobActive}>
            <Sparkles size={18} aria-hidden />
            AI로 추천받기
          </Button>
        </div>
        {jobActive && (
          <p className={styles.progress} role="status">
            <span className={styles.spinner} aria-hidden />
            {job.attempts > 0 ? '다시 시도하는 중…' : 'AI가 연습 과제를 만드는 중…'}
          </p>
        )}
        {message && <Card variant="soft">{message}</Card>}

        {items.length > 0 && (
          <ul className={styles.list}>
            {items.map((r) => (
              <li key={r.id}>
                <Card as={Link} to={`/growth/recommendations/${r.id}`} className={styles.row}>
                  <span className={styles.rowText}>
                    <span className={styles.caption}>
                      {options
                        ? labelOf(options.weakness_categories, r.weakness_category)
                        : r.weakness_category}{' '}
                      · {r.estimated_minutes}분 · {DIFFICULTY_LABELS[r.difficulty]}
                    </span>
                    <span className={styles.rowTitle}>{r.title}</span>
                  </span>
                  <Badge>{RECOMMENDATION_STATUS[r.status] ?? r.status}</Badge>
                  <ChevronRight size={20} aria-hidden />
                </Card>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  )
}

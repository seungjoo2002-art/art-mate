import { useCallback, useState } from 'react'
import { ChevronRight, Clock, Lightbulb } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import MascotCheer from '../../../components/mascot/MascotCheer'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { usePolling } from '../../../hooks/usePolling'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { generateRecommendations, getGrowthJob, listRecommendations } from '../api'
import { DIFFICULTY_LABELS, INSUFFICIENT_REASONS, RECOMMENDATION_STATUS } from '../labels'
import styles from './RecommendationsPage.module.css'

const HIDDEN = ['SUPERSEDED']
const ORDER = { ADOPTED: 0, DRAFT: 1, IN_REVIEW: 1, COMPLETED: 2, REJECTED: 3 }
// 상태별 배지 색 (진행 중 주황 · 새 추천 연주황 · 완료 초록 · 나머지 회색)
const STATUS_TONE = { ADOPTED: 'doing', DRAFT: 'new', IN_REVIEW: 'new', COMPLETED: 'done' }
// AI를 못 쓰는 경우 → 조용히 기본 추천으로
const AI_UNAVAILABLE = ['AI_CONSENT_REQUIRED', 'GROWTH_AI_NOT_CONFIGURED']

/**
 * 반복 약점 기반 맞춤 연습 과제 (개인).
 * 버튼 하나: AI 추천을 먼저 시도하고, AI를 못 쓰면(동의 없음·준비 안 됨·실패) 기본 추천으로 이어서 받음
 */
export default function RecommendationsPage() {
  const location = useLocation()
  const options = useOptions()
  const load = useCallback(() => listRecommendations(), [])
  const { data, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [job, setJob] = useState(null)
  const [needConsent, setNeedConsent] = useState(false)

  function showError(err) {
    setMessage(
      err.code === 'INSUFFICIENT_DATA'
        ? (INSUFFICIENT_REASONS[err.details?.reason] ?? '기록이 더 쌓이면 추천해 드릴게요.')
        : toErrorMessage(err),
    )
  }

  function handleResult(result) {
    if (result.status === 'QUEUED') {
      setJob(result.job)
      return
    }
    if (result.status === 'EXISTING')
      setMessage('새로 분석할 기록이 없어 지금 과제를 그대로 보여 드려요.')
    reload()
  }

  // 기본(규칙) 추천
  async function recommendBasic(note = '') {
    try {
      handleResult(await generateRecommendations({ useAi: false }))
      if (note) setMessage(note)
    } catch (err) {
      showError(err)
    }
  }

  async function recommend() {
    setBusy(true)
    setMessage('')
    try {
      handleResult(await generateRecommendations({ useAi: true }))
      setNeedConsent(false)
    } catch (err) {
      if (AI_UNAVAILABLE.includes(err.code)) {
        setNeedConsent(err.code === 'AI_CONSENT_REQUIRED')
        await recommendBasic()
      } else showError(err)
    } finally {
      setBusy(false)
    }
  }

  // AI 생성 작업 폴링 → 끝나면 목록 다시 조회, 실패하면 기본 추천으로
  const pollJob = useCallback(async () => {
    try {
      const next = await getGrowthJob(job.id)
      setJob(next)
      if (next.status === 'SUCCEEDED') reload()
      if (next.status === 'FAILED')
        await recommendBasic('아트메이트가 과제를 만들지 못해 기본 추천으로 준비했어요.')
      if (next.status === 'CANCELLED') setMessage('AI 성장 코칭 동의가 철회되어 취소됐어요.')
    } catch (err) {
      setMessage(toErrorMessage(err))
      setJob(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job, reload])
  const jobActive = ['QUEUED', 'RUNNING'].includes(job?.status)
  usePolling(jobActive, 5000, pollJob, [job])
  const working = busy || jobActive

  const items = (data?.items ?? [])
    .filter((r) => !HIDDEN.includes(r.status))
    .sort((a, b) => (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9))
  const category = (code) => (options ? labelOf(options.weakness_categories, code) : code)

  return (
    <>
      <TopBar title="맞춤 연습 과제" belowHeader />
      <main className={styles.body}>
        <MascotCheer
          pose="artist"
          eyebrow="맞춤 연습 과제"
          sub="여러 작품에서 반복해서 지적된 부분으로 과제를 만들어요."
        >
          약한 부분을 콕 집어 연습해 봐요
        </MascotCheer>

        <div className={styles.cta}>
          <button type="button" className={styles.button} onClick={recommend} disabled={working}>
            {working ? (
              <span className={styles.spinner} aria-hidden />
            ) : (
              <Lightbulb size={16} aria-hidden />
            )}
            {jobActive ? '과제 만드는 중…' : busy ? '추천하는 중…' : '과제 추천받기'}
          </button>
          {jobActive && (
            <p className={styles.hint} role="status">
              {job.attempts > 0
                ? '아트메이트가 다시 시도하고 있어요'
                : '아트메이트가 내 기록을 보고 과제를 만들고 있어요'}
            </p>
          )}
          {needConsent && !jobActive && (
            <Link
              to="/ai-consent?purpose=GROWTH_COACHING"
              state={{ from: location.pathname }}
              className={styles.consent}
            >
              AI 성장 코칭에 동의하면 더 꼼꼼한 과제를 받을 수 있어요
              <ChevronRight size={14} aria-hidden />
            </Link>
          )}
        </div>
        {message && <p className={styles.message}>{message}</p>}

        {items.length > 0 ? (
          <section className={styles.section}>
            <h2 className={styles.heading}>내 과제 {items.length}개</h2>
            <ul className={styles.list}>
              {items.map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/growth/recommendations/${r.id}`}
                    className={`${styles.card} ${r.status === 'REJECTED' ? styles.dim : ''}`}
                  >
                    <span className={styles.cardText}>
                      <span className={styles.topLine}>
                        <span className={styles.category}>{category(r.weakness_category)}</span>
                        <span
                          className={`${styles.status} ${styles[STATUS_TONE[r.status] ?? 'muted']}`}
                        >
                          {RECOMMENDATION_STATUS[r.status] ?? r.status}
                        </span>
                      </span>
                      <span className={styles.title}>{r.title}</span>
                      <span className={styles.meta}>
                        <Clock size={13} aria-hidden /> {r.estimated_minutes}분 ·{' '}
                        {DIFFICULTY_LABELS[r.difficulty]}
                      </span>
                    </span>
                    <ChevronRight size={18} className={styles.chevron} aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          data && (
            <p className={styles.empty}>
              아직 받은 과제가 없어요. 위 버튼을 눌러 첫 과제를 받아 보세요.
            </p>
          )
        )}
      </main>
    </>
  )
}

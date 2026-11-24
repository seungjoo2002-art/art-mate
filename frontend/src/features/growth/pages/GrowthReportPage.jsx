import { useCallback, useState } from 'react'
import { Bot } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { MASCOT_POSES } from '../../../components/mascot/poses'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { usePolling } from '../../../hooks/usePolling'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getReport, regenerateReport } from '../api'
import WeaknessAnalysis from '../components/WeaknessAnalysis'
import { PERIOD_LABELS } from '../labels'
import styles from './GrowthReportPage.module.css'

export default function GrowthReportPage() {
  const { reportId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const load = useCallback(() => getReport(reportId), [reportId])
  const { data: report, error, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  const narrative = report?.ai_narrative
  usePolling(narrative?.status === 'PENDING', 5000, reload, [report])

  if (error) {
    return (
      <FullScreenStatus title="리포트를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!report) return <FullScreenStatus />

  async function regenerate(includeAi) {
    setBusy(true)
    setActionError('')
    try {
      const next = await regenerateReport(report.id, includeAi)
      if (next.id !== report.id) navigate(`/growth/reports/${next.id}`, { replace: true })
      else reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const range = report.period_start
    ? `${formatDot(report.period_start)} ~ ${formatDot(report.period_end)}`
    : '처음부터 지금까지'

  return (
    <>
      <TopBar title="성장 리포트" belowHeader />
      <main className={styles.body}>
        {/* 계단 오르는 고양이 + 기간 */}
        <div className={styles.hero}>
          <img src={MASCOT_POSES.growth} alt="" className={styles.heroCat} />
          <div className={styles.heroText}>
            <span className={styles.heroPeriod}>{PERIOD_LABELS[report.period_type]}</span>
            <p className={styles.heroTitle}>한 계단씩 올라가는 중이에요!</p>
            <span className={styles.heroRange}>{range}</span>
          </div>
        </div>

        {report.is_stale && (
          <div className={styles.stale}>
            <span>리포트를 만든 뒤 기록이 바뀌었어요.</span>
            <button
              type="button"
              className={styles.smallButton}
              onClick={() => regenerate(narrative?.status === 'READY')}
              disabled={busy}
            >
              다시 만들기
            </button>
          </div>
        )}

        <WeaknessAnalysis analysis={report.statistics} />

        <Narrative
          narrative={narrative}
          busy={busy}
          onRequest={() => regenerate(true)}
          onConsent={() =>
            navigate('/ai-consent?purpose=GROWTH_COACHING', { state: { from: location.pathname } })
          }
        />
        {actionError && <p className={styles.error}>{actionError}</p>}
      </main>
    </>
  )
}

/** "2026-11-01" → "11.1" */
function formatDot(iso) {
  const [, m, d] = iso.split('-').map(Number)
  return `${m}.${d}`
}

/** AI 설명문 (통계와 분리해서 "AI가 정리한 설명"으로 표시) */
function Narrative({ narrative, busy, onRequest, onConsent }) {
  if (!narrative) return null
  const { status, error_code: code, content } = narrative

  if (status === 'READY' && content) {
    return (
      <section className={styles.aiCard}>
        <span className={styles.aiLabel}>
          <Bot size={14} aria-hidden /> 아트메이트가 정리한 설명
        </span>
        <p>{content.overview}</p>
        {content.strengths_comment && <p>{content.strengths_comment}</p>}
        {content.improvement_comment && <p>{content.improvement_comment}</p>}
        {content.next_goals?.length > 0 && (
          <ul className={styles.steps}>
            {content.next_goals.map((g) => (
              <li key={g.goal}>{g.goal}</li>
            ))}
          </ul>
        )}
      </section>
    )
  }
  if (status === 'PENDING') {
    return (
      <p className={styles.progress} role="status">
        <span className={styles.spinner} aria-hidden />
        아트메이트가 설명을 정리하는 중…
      </p>
    )
  }
  if (status === 'SKIPPED' && code === 'GROWTH_AI_NOT_CONFIGURED') return null
  if (status === 'SKIPPED' && code === 'INSUFFICIENT_DATA') return null
  if (status === 'SKIPPED' && ['AI_CONSENT_REQUIRED', 'AI_CONSENT_REVOKED'].includes(code)) {
    return (
      <div className={styles.aiAsk}>
        <span>아트메이트 설명을 받으려면 AI 성장 코칭 동의가 필요해요.</span>
        <button type="button" className={styles.smallButton} onClick={onConsent}>
          동의하러 가기
        </button>
      </div>
    )
  }

  const message =
    status === 'FAILED'
      ? '설명을 만들지 못했어요.'
      : status === 'INVALIDATED'
        ? '근거 첨삭이 지워져서 설명도 지웠어요.'
        : null
  return (
    <div className={styles.aiAsk}>
      <span>{message ?? '아트메이트가 이 기간을 글로 정리해 줄 수도 있어요.'}</span>
      <button type="button" className={styles.smallButton} onClick={onRequest} disabled={busy}>
        <Bot size={14} aria-hidden />
        {busy ? '요청하는 중…' : message ? '다시 받기' : '설명 받기'}
      </button>
    </div>
  )
}

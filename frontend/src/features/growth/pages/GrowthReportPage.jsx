import { useCallback, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { usePolling } from '../../../hooks/usePolling'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getReport, regenerateReport } from '../api'
import WeaknessAnalysis from '../components/WeaknessAnalysis'
import { PERIOD_LABELS } from '../labels'
import styles from './GrowthPage.module.css'

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

  return (
    <>
      <TopBar title="성장 리포트" belowHeader />
      <main className={styles.body}>
        <div>
          <p className={styles.label}>{PERIOD_LABELS[report.period_type]}</p>
          <p className={styles.caption}>
            {report.period_start ? `${report.period_start} ~ ${report.period_end}` : '전체 기간'} ·
            확정 첨삭 {report.source_feedback_count}개 기준
          </p>
        </div>

        {report.is_stale && (
          <Card variant="soft" className={styles.aiCard}>
            리포트를 만든 뒤 기록이 바뀌었어요.
            <Button
              size="md"
              variant="soft"
              onClick={() => regenerate(narrative?.status === 'READY')}
              disabled={busy}
            >
              최신 기록으로 다시 만들기
            </Button>
          </Card>
        )}

        <Narrative
          narrative={narrative}
          busy={busy}
          onRequest={() => regenerate(true)}
          onConsent={() =>
            navigate('/ai-consent?purpose=GROWTH_COACHING', { state: { from: location.pathname } })
          }
        />
        {actionError && <p className={styles.error}>{actionError}</p>}

        <WeaknessAnalysis analysis={report.statistics} />
      </main>
    </>
  )
}

/** AI 설명문 (통계와 분리해서 "AI가 정리한 설명"으로 표시) */
function Narrative({ narrative, busy, onRequest, onConsent }) {
  if (!narrative) return null
  const { status, error_code: code, content } = narrative

  if (status === 'READY' && content) {
    return (
      <Card variant="soft" className={styles.aiCard}>
        <span className={styles.aiLabel}>
          <Sparkles size={14} aria-hidden /> AI가 정리한 설명
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
      </Card>
    )
  }
  if (status === 'PENDING') {
    return (
      <p className={styles.progress} role="status">
        <span className={styles.spinner} aria-hidden />
        AI가 설명을 정리하는 중…
      </p>
    )
  }
  if (status === 'SKIPPED' && code === 'GROWTH_AI_NOT_CONFIGURED') return null
  if (status === 'SKIPPED' && code === 'INSUFFICIENT_DATA') return null
  if (status === 'SKIPPED' && ['AI_CONSENT_REQUIRED', 'AI_CONSENT_REVOKED'].includes(code)) {
    return (
      <Card variant="soft" className={styles.aiCard}>
        AI 설명을 받으려면 AI 성장 코칭 동의가 필요해요.
        <Button size="md" onClick={onConsent}>
          동의하러 가기
        </Button>
      </Card>
    )
  }

  const message =
    status === 'FAILED'
      ? 'AI 설명을 만들지 못했어요.'
      : status === 'INVALIDATED'
        ? '근거 첨삭이 삭제되어 AI 설명을 지웠어요.'
        : null
  return (
    <Card variant="soft" className={styles.aiCard}>
      {message ?? '통계 외에 AI가 정리한 설명도 받을 수 있어요.'}
      <Button size="md" onClick={onRequest} disabled={busy}>
        <Sparkles size={18} aria-hidden />
        {busy ? '요청하는 중…' : message ? 'AI 설명 다시 받기' : 'AI 설명 받기'}
      </Button>
    </Card>
  )
}

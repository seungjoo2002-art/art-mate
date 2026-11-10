import { useState } from 'react'
import { ChevronRight, Pencil, Sparkles, Trash2 } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { usePolling } from '../../../hooks/usePolling'
import { labelOf } from '../../../lib/options'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getAiConsent } from '../aiApi'
import { deleteNote, requestNoteSummary } from '../notesApi'
import aiStyles from './RecordingAiStatus.module.css'
import styles from './NoteCard.module.css'

const ACTIVE = ['QUEUED', 'RUNNING']
const NOT_CONFIGURED = ['AI_NOT_CONFIGURED']

/** 타임라인의 텍스트 첨삭 카드. onChanged: 목록 다시 불러오기 */
export default function NoteCard({ note, options, onChanged }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const job = note.summary_job
  const summarizing = !note.feedback_id && ACTIVE.includes(job?.status)
  usePolling(summarizing, job?.attempts > 0 ? 10_000 : 5_000, onChanged, [note])

  const sourceLabel = options ? labelOf(options.feedback_sources, note.source) : note.source
  const long = note.body.length > 120

  async function run(action) {
    setBusy(true)
    setError(null)
    try {
      await action()
      onChanged()
    } catch (err) {
      if (err.code === 'AI_CONSENT_REQUIRED') {
        navigate('/ai-consent', { state: { from: location.pathname } })
        return
      }
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function summarize({ regenerate = false } = {}) {
    const consent = await getAiConsent()
    if (!consent.is_valid) {
      navigate('/ai-consent', { state: { from: location.pathname } })
      return
    }
    await requestNoteSummary(note.id, { regenerate })
  }

  function handleDelete() {
    if (!window.confirm('이 첨삭을 삭제할까요? AI 정리도 함께 삭제되고 성장 분석에서 빠져요.'))
      return
    run(() => deleteNote(note.id))
  }

  const failed = !note.feedback_id && job?.status === 'FAILED'

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.source}>
          <Pencil size={14} aria-hidden />
          {sourceLabel}
          {note.feedback_date && (
            <span className={styles.date}> · {formatMonthDay(note.feedback_date)}</span>
          )}
        </span>
        <Link
          to={`/feedback-notes/${note.id}/edit`}
          state={{ from: location.pathname }}
          className={styles.icon}
          aria-label="첨삭 수정"
        >
          <Pencil size={18} />
        </Link>
        <button
          type="button"
          className={styles.icon}
          onClick={handleDelete}
          disabled={busy}
          aria-label="첨삭 삭제"
        >
          <Trash2 size={18} />
        </button>
      </div>

      <p className={`${styles.body} ${long && !expanded ? styles.clamped : ''}`}>{note.body}</p>
      {long && (
        <button type="button" className={styles.more} onClick={() => setExpanded((v) => !v)}>
          {expanded ? '접기' : '더 보기'}
        </button>
      )}

      <div className={aiStyles.status}>
        {error && NOT_CONFIGURED.includes(error.code) ? (
          <p className={aiStyles.muted}>{toErrorMessage(error)}</p>
        ) : note.feedback_id ? (
          <Link to={`/feedbacks/${note.feedback_id}`} className={aiStyles.result}>
            <Sparkles size={18} aria-hidden />
            <span className={aiStyles.resultText}>AI 정리 결과 보기</span>
            <span className={note.feedback_status === 'APPROVED' ? aiStyles.done : aiStyles.todo}>
              {note.feedback_status === 'APPROVED' ? '확정됨' : '확인 필요'}
            </span>
            <ChevronRight size={18} aria-hidden />
          </Link>
        ) : summarizing ? (
          <p className={aiStyles.progress} role="status">
            <span className={aiStyles.spinner} aria-hidden />
            {job.attempts > 0 ? '다시 시도하는 중…' : 'AI가 정리하는 중…'}
          </p>
        ) : failed ? (
          <div className={aiStyles.failed}>
            <span>AI가 정리하지 못했어요.</span>
            {job.retryable && (
              <button
                type="button"
                className={aiStyles.link}
                onClick={() => run(summarize)}
                disabled={busy}
              >
                다시 시도
              </button>
            )}
          </div>
        ) : (
          <button
            type="button"
            className={aiStyles.action}
            onClick={() => run(summarize)}
            disabled={busy}
          >
            <Sparkles size={18} aria-hidden />
            {busy ? '요청하는 중…' : 'AI로 정리하기'}
          </button>
        )}
        {error && !NOT_CONFIGURED.includes(error.code) && (
          <p className={aiStyles.error}>{toErrorMessage(error)}</p>
        )}
      </div>
    </div>
  )
}

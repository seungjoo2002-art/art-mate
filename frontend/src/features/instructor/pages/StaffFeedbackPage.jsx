import { useCallback, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import { Button, Card, Textarea } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  approveStaffFeedback,
  getStaffFeedback,
  getStaffRecordingUrl,
  rejectStaffFeedback,
  reopenStaffFeedback,
  updateStaffFeedback,
} from '../../academy/api'
import FeedbackContent from '../../feedback/components/FeedbackContent'
import FeedbackEditor from '../../feedback/components/FeedbackEditor'
import { useEvidencePlayer } from '../../feedback/useEvidencePlayer'
import { FEEDBACK_STATUS, formatClock, formatDateTime } from '../status'
import StatusBadge from '../StatusBadge'
import styles from '../Instructor.module.css'

/**
 * 첨삭 검토 (담당 강사): 원문(녹음 전사·글 첨삭) ↔ AI 정리·9개 태그를 나란히 보고 수정·승인·반려.
 * 승인하면 학생 화면에 '확정됨'으로 보인다. 수정·승인은 version으로 동시 수정을 막는다.
 */
export default function StaffFeedbackPage() {
  const { academy } = useOutletContext()
  const { feedbackId } = useParams()
  const base = `/instructor/academies/${academy.id}`
  const load = useCallback(() => getStaffFeedback(academy.id, feedbackId), [academy.id, feedbackId])
  const { data: feedback, error, reload } = useAsync(load)
  const options = useOptions()
  const fetchUrl = useCallback(
    (artworkId, recordingId) => getStaffRecordingUrl(academy.id, artworkId, recordingId),
    [academy.id],
  )
  const player = useEvidencePlayer(feedback?.artwork_id, feedback?.recording_id, fetchUrl)
  const [mode, setMode] = useState('view') // view | edit | reject
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  if (error) {
    return (
      <div className={styles.empty}>
        <p>{toErrorMessage(error)}</p>
        <Link to={`${base}/feedbacks`} className={styles.link}>
          검토 목록으로
        </Link>
      </div>
    )
  }
  if (!feedback) return <p className={styles.hint}>불러오는 중…</p>

  const approved = feedback.status === 'APPROVED'
  const reviewable = feedback.status === 'DRAFT' || feedback.status === 'IN_REVIEW'

  async function run(action, { after } = {}) {
    setBusy(true)
    setActionError('')
    try {
      await action()
      after?.()
      reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
      if (err.code === 'FEEDBACK_VERSION_CONFLICT') {
        setMode('view')
        reload()
      }
    } finally {
      setBusy(false)
    }
  }

  const source = feedback.source_segments ?? []

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <Link to={`${base}/feedbacks`} className={styles.link}>
            &lt; 검토 목록
          </Link>
          <h1 className={styles.title}>{feedback.artwork_title}</h1>
          <p className={styles.subtitle}>
            {feedback.student?.display_name} · {feedback.recording_id ? '녹음 첨삭' : '글 첨삭'} ·{' '}
            {feedback.stage_name ? `${feedback.stage_name} 단계` : '작품 전체'} ·{' '}
            {formatDateTime(feedback.created_at)}
          </p>
        </div>
        <StatusBadge status={FEEDBACK_STATUS[feedback.status]} fallback={feedback.status} />
      </div>

      <div className={styles.twoCol}>
        <section className={styles.section} aria-label="AI 첨삭 정리">
          {mode === 'edit' ? (
            <FeedbackEditor
              feedback={feedback}
              options={options}
              saving={busy}
              onSave={(body) =>
                run(
                  () =>
                    updateStaffFeedback(academy.id, feedback.id, {
                      version: feedback.version,
                      ...body,
                    }),
                  { after: () => setMode('view') },
                )
              }
              onCancel={() => setMode('view')}
            />
          ) : (
            <>
              {!approved && (
                <Card variant="soft">
                  AI가 정리한 초안이에요. 왼쪽 원문과 비교해 틀린 부분을 고친 뒤 승인하면 학생에게
                  확정된 첨삭으로 보여요.
                </Card>
              )}
              {feedback.rejected_reason && (
                <p className={styles.hint}>반려 사유: {feedback.rejected_reason}</p>
              )}
              <FeedbackContent feedback={feedback} options={options} player={player} />
              {player.error && <p className={styles.error}>{player.error}</p>}
            </>
          )}

          {actionError && <p className={styles.error}>{actionError}</p>}

          {mode === 'reject' && (
            <Card>
              <form
                className={styles.form}
                onSubmit={(e) => {
                  e.preventDefault()
                  run(() => rejectStaffFeedback(academy.id, feedback.id, feedback.version, reason.trim()), {
                    after: () => {
                      setMode('view')
                      setReason('')
                    },
                  })
                }}
              >
                <Textarea
                  label="반려 사유 (학생에게는 보이지 않아요)"
                  rows={3}
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <div className={styles.rowActions}>
                  <button type="submit" className={styles.smallPrimary} disabled={!reason.trim() || busy}>
                    반려하기
                  </button>
                  <button type="button" className={styles.smallButton} onClick={() => setMode('view')}>
                    취소
                  </button>
                </div>
              </form>
            </Card>
          )}

          {mode === 'view' && (
            <div className={styles.rowActions}>
              {reviewable && (
                <>
                  <Button
                    size="md"
                    fullWidth={false}
                    disabled={busy}
                    onClick={() => run(() => approveStaffFeedback(academy.id, feedback.id, feedback.version))}
                  >
                    {busy ? '처리하는 중…' : '승인하기'}
                  </Button>
                  <Button size="md" variant="soft" fullWidth={false} disabled={busy} onClick={() => setMode('edit')}>
                    수정하기
                  </Button>
                  <Button size="md" variant="soft" fullWidth={false} disabled={busy} onClick={() => setMode('reject')}>
                    반려하기
                  </Button>
                </>
              )}
              {approved && (
                <Button
                  size="md"
                  variant="soft"
                  fullWidth={false}
                  disabled={busy}
                  onClick={() => run(() => reopenStaffFeedback(academy.id, feedback.id, feedback.version))}
                >
                  승인 취소하고 다시 검토
                </Button>
              )}
            </div>
          )}
        </section>

        <aside className={styles.section} aria-label="첨삭 원문">
          <h2 className={styles.sectionTitle}>
            {feedback.recording_id ? '녹음 전사 원문' : '첨삭 원문'}
          </h2>
          {source.length === 0 ? (
            <p className={styles.empty}>원문을 불러올 수 없어요.</p>
          ) : (
            <ol className={styles.transcript}>
              {source.map((seg) => (
                <li key={seg.index}>
                  {seg.start_ms != null && <span className={styles.time}>{formatClock(seg.start_ms)}</span>}
                  {seg.text}
                </li>
              ))}
            </ol>
          )}
          <Link to={`${base}/artworks/${feedback.artwork_id}`} className={styles.link}>
            작품·사진 보기 &gt;
          </Link>
        </aside>
      </div>
    </>
  )
}

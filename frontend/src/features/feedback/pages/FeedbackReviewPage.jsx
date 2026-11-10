import { useCallback, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Badge, Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { approveFeedback, getFeedback, reopenFeedback, updateFeedback } from '../aiApi'
import FeedbackEditor from '../components/FeedbackEditor'
import { KINDS, ORIGIN_LABELS } from '../feedbackKinds'
import { useEvidencePlayer } from '../useEvidencePlayer'
import styles from './FeedbackReviewPage.module.css'

const STATUS_LABELS = { DRAFT: '확인 필요', IN_REVIEW: '확인 필요', APPROVED: '확정됨', REJECTED: '반려됨' }

/** AI 정리 결과 보기·수정·확정 (개인 작품은 학생 본인이 확정: review_mode SELF) */
export default function FeedbackReviewPage() {
  const { feedbackId } = useParams()
  const load = useCallback(() => getFeedback(feedbackId), [feedbackId])
  const { data: feedback, error, reload } = useAsync(load)
  const options = useOptions()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const player = useEvidencePlayer(feedback?.artwork_id, feedback?.recording_id)

  if (error) {
    return (
      <FullScreenStatus title="정리 결과를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!feedback) return <FullScreenStatus />

  const canReview = feedback.review_mode === 'SELF'
  const approved = feedback.status === 'APPROVED'
  const kindLabel = (kind, fallback) =>
    options ? labelOf(options.feedback_item_kinds, kind) : fallback
  const categoryLabel = (code) => (options ? labelOf(options.weakness_categories, code) : code)

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
        setEditing(false)
        reload()
      }
    } finally {
      setBusy(false)
    }
  }

  const handleSave = (body) =>
    run(() => updateFeedback(feedback.id, { version: feedback.version, ...body }), {
      after: () => setEditing(false),
    })

  return (
    <>
      <TopBar
        title={feedback.artwork_title ?? 'AI 정리 결과'}
        belowHeader
        right={
          <span className={approved ? styles.statusDone : styles.statusTodo}>
            {STATUS_LABELS[feedback.status] ?? feedback.status}
          </span>
        }
      />
      <main className={styles.body}>
        {editing ? (
          <FeedbackEditor
            feedback={feedback}
            options={options}
            saving={busy}
            onSave={handleSave}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <>
            {!approved && canReview && (
              <Card variant="soft" className={styles.notice}>
                AI가 녹음 내용을 정리한 초안이에요. 내용을 확인하고 틀린 부분은 고친 뒤 확정해 주세요.
              </Card>
            )}

            <section className={styles.section}>
              <h2 className={styles.label}>핵심 요약</h2>
              <p className={styles.summary}>{feedback.summary}</p>
              {feedback.categories.length > 0 && (
                <div className={styles.chips}>
                  {feedback.categories.map((code) => (
                    <Badge key={code}>{categoryLabel(code)}</Badge>
                  ))}
                </div>
              )}
            </section>

            {KINDS.map(({ kind, field, label }) =>
              feedback[field].length === 0 ? null : (
                <section key={kind} className={styles.section}>
                  <h2 className={styles.label}>{kindLabel(kind, label)}</h2>
                  <ul className={styles.items}>
                    {feedback[field].map((item) => (
                      <li key={item.id} className={styles.item}>
                        <p>{item.content}</p>
                        <div className={styles.meta}>
                          {item.category && <span className={styles.tag}>{categoryLabel(item.category)}</span>}
                          {ORIGIN_LABELS[item.origin] && (
                            <span className={styles.origin}>{ORIGIN_LABELS[item.origin]}</span>
                          )}
                          {item.evidence[0]?.start_ms != null && (
                            <button
                              type="button"
                              className={styles.listen}
                              onClick={() =>
                                player.play(item.id, item.evidence[0].start_ms, item.evidence.at(-1).end_ms)
                              }
                            >
                              {player.playingKey === item.id ? <Pause size={14} /> : <Play size={14} />}
                              근거 듣기
                            </button>
                          )}
                        </div>
                        {item.evidence.some((e) => e.text) && (
                          <p className={styles.evidence}>
                            “{item.evidence.map((e) => e.text).filter(Boolean).join(' ')}”
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              ),
            )}
            {player.error && <p className={styles.error}>{player.error}</p>}
            {actionError && <p className={styles.error}>{actionError}</p>}

            {canReview ? (
              <div className={styles.actions}>
                {approved ? (
                  <Button
                    variant="soft"
                    disabled={busy}
                    onClick={() => run(() => reopenFeedback(feedback.id, feedback.version))}
                  >
                    확정 취소하고 수정하기
                  </Button>
                ) : (
                  <>
                    <Button
                      disabled={busy}
                      onClick={() => run(() => approveFeedback(feedback.id, feedback.version))}
                    >
                      {busy ? '처리하는 중…' : '이대로 확정하기'}
                    </Button>
                    <Button variant="soft" disabled={busy} onClick={() => setEditing(true)}>
                      수정하기
                    </Button>
                  </>
                )}
              </div>
            ) : (
              <p className={styles.hint}>선생님이 확인한 정리예요.</p>
            )}
          </>
        )}
      </main>
    </>
  )
}

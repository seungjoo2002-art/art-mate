import { useCallback, useEffect, useState } from 'react'
import { Check, Pause, PencilLine, Play } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Badge, Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { approveFeedback, getFeedback, reopenFeedback, updateFeedback } from '../aiApi'
import FeedbackEditor from '../components/FeedbackEditor'
import { getGrowthSummary } from '../../growth/api'
import { ORIGIN_LABELS } from '../feedbackKinds'
import { displayTags, repeatedWeaknesses } from '../reviewSections'
import { useEvidencePlayer } from '../useEvidencePlayer'
import styles from './FeedbackReviewPage.module.css'

const STATUS_LABELS = {
  DRAFT: '확인 필요',
  IN_REVIEW: '확인 필요',
  APPROVED: '확정됨',
  REJECTED: '반려됨',
}

/** AI 정리 결과 보기·수정·확정 (개인 작품은 학생 본인이 확정: review_mode SELF) */
export default function FeedbackReviewPage() {
  const { feedbackId } = useParams()
  const load = useCallback(() => getFeedback(feedbackId), [feedbackId])
  const { data: feedback, error, reload } = useAsync(load)
  const options = useOptions()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  // v1.2 확정·확정 취소 직후 안내 (성장 분석·홈 브리핑 반영 여부)
  const [decision, setDecision] = useState(null)
  const player = useEvidencePlayer(feedback?.artwork_id, feedback?.recording_id)
  const [growth, setGrowth] = useState(null) // 반복 약점 판단용 (확정 첨삭 기준 통계)

  useEffect(() => {
    let alive = true
    getGrowthSummary()
      .then((value) => alive && setGrowth(value))
      .catch(() => alive && setGrowth(null))
    return () => {
      alive = false
    }
  }, [feedbackId])

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
  const repeated = repeatedWeaknesses(feedback, growth)
  const tags = displayTags(feedback, categoryLabel)

  const renderItems = (items) =>
    items.length === 0 ? (
      <p className={styles.empty}>언급되지 않음</p>
    ) : (
      <ul className={styles.items}>
        {items.map((item) => (
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
              <details className={styles.evidence}>
                <summary>첨삭 원문 보기</summary>
                <p>
                  “
                  {item.evidence
                    .map((e) => e.text)
                    .filter(Boolean)
                    .join(' ')}
                  ”
                </p>
              </details>
            )}
          </li>
        ))}
      </ul>
    )

  async function run(action, { after } = {}) {
    setBusy(true)
    setActionError('')
    setDecision(null)
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
        title={feedback.artwork_title ?? '아트메이트 정리 결과'}
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
            {decision === 'approved' && approved && (
              <Card variant="soft" className={styles.done} role="status">
                <strong>첨삭을 확정했어요.</strong>
                <span>아카이브 분석 리포트와 홈 오늘의 브리핑에 반영돼요.</span>
                <div className={styles.doneLinks}>
                  <Link to="/archive?tab=report">분석 리포트 보기</Link>
                  <Link to="/home">홈 브리핑 보기</Link>
                </div>
              </Card>
            )}
            {decision === 'reopened' && !approved && (
              <Card variant="soft" className={styles.notice} role="status">
                확정을 취소했어요. 다시 확정하기 전까지는 성장 분석과 홈 브리핑에서 빠져요.
              </Card>
            )}
            {!approved && canReview && decision !== 'reopened' && (
              <Card variant="soft" className={styles.notice}>
                아트메이트가 첨삭을 정리해 두었어요. 맞게 정리됐는지 살펴보고, 다른 부분은 고친 뒤
                아래
                <strong> 확정하기</strong>를 눌러 주세요. 확정한 첨삭부터 성장 기록과 홈 브리핑에
                담겨요.
              </Card>
            )}
            {feedback.recording_id && (
              <Link
                to={`/artworks/${feedback.artwork_id}/recordings/${feedback.recording_id}/transcript`}
                className={styles.transcriptLink}
              >
                녹음 대본 보기 · 고치기 &gt;
              </Link>
            )}

            <section className={styles.section}>
              <h2 className={styles.label}>전체 첨삭 요약</h2>
              {feedback.summary ? (
                <p className={styles.summary}>{feedback.summary}</p>
              ) : (
                <p className={styles.empty}>언급되지 않음</p>
              )}
              {tags.length > 0 && (
                <>
                  <ul className={styles.chips} aria-label="첨삭 분류">
                    {tags.map((tag) => (
                      <li key={tag.key}>
                        <Badge className={tag.needsWork ? undefined : styles.tagPraise}>
                          {tag.label}
                          <span className={styles.srOnly}>
                            {tag.needsWork ? ' (개선할 점 있음)' : ' (잘한 점)'}
                          </span>
                        </Badge>
                      </li>
                    ))}
                  </ul>
                  {tags.some((t) => !t.needsWork) && tags.some((t) => t.needsWork) && (
                    <p className={styles.tagLegend} aria-hidden>
                      주황색은 개선할 점이 나온 주제예요.
                    </p>
                  )}
                </>
              )}
              {/* v0.9.7 어느 단계의 피드백인지 */}
              <div className={styles.chips}>
                <Badge>
                  {feedback.stage_name ? `${feedback.stage_name} 단계 피드백` : '작품 전체 피드백'}
                </Badge>
                {/* v0.9.8 원본 피드백의 기준 사진 (전사·요약도 같은 연결) */}
                <Badge>{refsLabel(feedback.image_refs)}</Badge>
              </div>
            </section>

            {/* 메모지: 잘한 점(아이보리) · 개선할 점(연한 주황) */}
            <section className={`${styles.section} ${styles.memo} ${styles.memoGood}`}>
              <h2 className={styles.label}>
                <Check size={16} strokeWidth={2.4} aria-hidden /> 잘한 점
              </h2>
              {renderItems(feedback.strengths)}
            </section>

            <section className={`${styles.section} ${styles.memo} ${styles.memoFix}`}>
              <h2 className={styles.label}>
                <PencilLine size={16} strokeWidth={2.2} aria-hidden /> 개선할 점
              </h2>
              {feedback.weaknesses.length === 0 && feedback.fixes.length === 0 ? (
                <p className={styles.empty}>언급되지 않음</p>
              ) : (
                <>
                  {feedback.weaknesses.length > 0 && (
                    <div className={styles.subBlock}>
                      <h3 className={styles.subLabel}>{kindLabel('WEAKNESS', '부족한 점')}</h3>
                      {renderItems(feedback.weaknesses)}
                    </div>
                  )}
                  {feedback.fixes.length > 0 && (
                    <div className={`${styles.subBlock} ${styles.subBlockFix}`}>
                      <h3 className={styles.subLabel}>이렇게 수정해 보세요</h3>
                      {renderItems(feedback.fixes)}
                    </div>
                  )}
                </>
              )}
            </section>

            <section className={styles.section}>
              <h2 className={styles.label}>반복 약점</h2>
              {repeated.status === 'found' ? (
                <>
                  <div className={styles.chips}>
                    {repeated.items.map((item) => (
                      <Badge key={item.category}>{categoryLabel(item.category)}</Badge>
                    ))}
                  </div>
                  <p className={styles.hint}>
                    이전에 확정한 첨삭에서도 지적된 약점이에요 (
                    {repeated.items.map((item) => `${categoryLabel(item.category)} ${item.artworkCount}작품`).join(', ')}
                    ).
                  </p>
                </>
              ) : (
                <p className={styles.empty}>
                  {repeated.status === 'insufficient'
                    ? '아직 확정한 첨삭이 적어서 반복 약점을 판단하기 어려워요.'
                    : repeated.status === 'none'
                      ? '이번 첨삭에서 이전과 반복된 약점은 없어요.'
                      : '반복 약점 정보를 불러오지 못했어요.'}
                </p>
              )}
            </section>

            <section className={styles.section}>
              <h2 className={styles.label}>다음 작품 연습 과제</h2>
              {renderItems(feedback.next_tips)}
            </section>
            {player.error && <p className={styles.error}>{player.error}</p>}
            {actionError && <p className={styles.error}>{actionError}</p>}

            {canReview ? (
              <div className={approved ? styles.actions : `${styles.actions} ${styles.actionsSticky}`}>
                {approved ? (
                  <Button
                    variant="soft"
                    disabled={busy}
                    onClick={() =>
                      run(() => reopenFeedback(feedback.id, feedback.version), {
                        after: () => setDecision('reopened'),
                      })
                    }
                  >
                    확정 취소하고 수정하기
                  </Button>
                ) : (
                  <>
                    <Button
                      disabled={busy}
                      onClick={() =>
                        run(() => approveFeedback(feedback.id, feedback.version), {
                          after: () => setDecision('approved'),
                        })
                      }
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

/** 기준 사진 상태 한 줄 (사진은 작품 화면에서 확인·변경) */
function refsLabel(refs) {
  const count = refs?.photos?.length ?? 0
  if (refs?.status === 'CONFIRMED') return `기준 사진 ${count}장 · 확인됨`
  if (refs?.status === 'SUGGESTED') return `기준 사진 ${count}장 · 확인 필요`
  return '기준 사진 없음'
}

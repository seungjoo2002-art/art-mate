import { useCallback, useState } from 'react'
import { ChevronRight, ClipboardCheck, Clock } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { MASCOT_POSES } from '../../../components/mascot/poses'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  adoptRecommendation,
  getFollowUp,
  getRecommendation,
  listLinkedArtworks,
  rejectRecommendation,
  setRecommendationCompleted,
  startRecommendation,
  unlinkArtwork,
} from '../api'
import Notes from '../components/Notes'
import { DIFFICULTY_LABELS, FOLLOW_UP_LABELS, RECOMMENDATION_STATUS } from '../labels'
import styles from './RecommendationPage.module.css'

/** 맞춤 연습 과제 상세: 채택 → 시작 → 수행 작품 → 후속 분석 → 완료 (v0.9 F-8) */
export default function RecommendationPage() {
  const { recommendationId } = useParams()
  const navigate = useNavigate()
  const options = useOptions()
  const load = useCallback(() => getRecommendation(recommendationId), [recommendationId])
  const { data: rec, error, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  if (error) {
    return (
      <FullScreenStatus title="과제를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!rec) return <FullScreenStatus />

  const inProgress = ['ADOPTED', 'COMPLETED'].includes(rec.status)

  async function run(action) {
    setBusy(true)
    setActionError('')
    try {
      await action()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusy(false)
      reload()
    }
  }

  function handleReject() {
    const reason = window.prompt('거절하는 이유를 적어 주세요. (예: 이번 주는 다른 과제가 있음)')
    if (!reason?.trim()) return
    run(() => rejectRecommendation(rec.id, rec.version, reason.trim()))
  }

  const category = options
    ? labelOf(options.weakness_categories, rec.weakness_category)
    : rec.weakness_category
  const level = { EASY: 1, NORMAL: 2, HARD: 3 }[rec.difficulty] ?? 2

  return (
    <>
      <TopBar title="연습 과제" belowHeader />
      <main className={styles.body}>
        {/* 연습장 한 장: 분류·상태 → 제목 → 시간·난이도 → 설명 → 연습 방법(번호 줄) */}
        <article className={styles.notebook}>
          <div className={styles.tags}>
            <span className={styles.category}>{category}</span>
            {rec.source === 'AI' && <span className={styles.tagMuted}>아트메이트 추천</span>}
            <span className={`${styles.state} ${styles[rec.status] ?? ''}`}>
              {RECOMMENDATION_STATUS[rec.status] ?? rec.status}
            </span>
          </div>
          <h1 className={styles.title}>{rec.title}</h1>
          <p className={styles.meta}>
            <Clock size={13} aria-hidden /> 약 {rec.estimated_minutes}분
            <span
              className={styles.level}
              aria-label={`난이도 ${DIFFICULTY_LABELS[rec.difficulty]}`}
            >
              {[1, 2, 3].map((n) => (
                <i key={n} className={n <= level ? styles.on : ''} />
              ))}
            </span>
            {DIFFICULTY_LABELS[rec.difficulty]}
          </p>
          {rec.description && <p className={styles.desc}>{rec.description}</p>}

          {rec.method_steps?.length > 0 && (
            <>
              <h2 className={styles.subhead}>이렇게 연습해요</h2>
              <ol className={styles.steps}>
                {rec.method_steps.map((step, i) => (
                  <li key={step}>
                    <span className={styles.stepNo}>{i + 1}</span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </article>

        {/* 왜 이 과제? 선생님 고양이가 이유와 첨삭 문장을 말해 줌 */}
        <section className={styles.why} aria-label="추천 이유">
          <img src={MASCOT_POSES.teacher} alt="" className={styles.whyCat} />
          <div className={styles.whyBubbles}>
            <p className={`${styles.bubble} ${styles.bubbleLead}`}>
              {rec.reason || '이 부분을 자주 짚어 줬어요'}
            </p>
            {rec.evidence?.slice(0, 3).map((e) => (
              <Link key={e.item_id} to={`/feedbacks/${e.feedback_id}`} className={styles.bubble}>
                <span>“{e.content}”</span>
                {e.artwork_title && (
                  <span className={styles.source}>
                    {e.artwork_title}
                    {e.work_date && ` · ${formatMonthDay(e.work_date)}`} 첨삭에서
                  </span>
                )}
              </Link>
            ))}
          </div>
        </section>

        {inProgress && <PracticeProgress rec={rec} busy={busy} onRun={run} onReload={reload} />}

        {actionError && <p className={styles.error}>{actionError}</p>}

        {/* 버튼: 오른쪽 작은 주황 알약 + 왼쪽 글자 버튼 */}
        <div className={styles.actions}>
          {['DRAFT', 'IN_REVIEW'].includes(rec.status) && (
            <>
              <button
                type="button"
                className={styles.textButton}
                onClick={handleReject}
                disabled={busy}
              >
                이번엔 넘어가기
              </button>
              <button
                type="button"
                className={styles.pill}
                onClick={() => run(() => adoptRecommendation(rec.id, rec.version))}
                disabled={busy}
              >
                이 과제 해 볼래요!
              </button>
            </>
          )}
          {rec.status === 'ADOPTED' && !rec.started_at && (
            <button
              type="button"
              className={styles.pill}
              onClick={() => run(() => startRecommendation(rec.id, rec.version))}
              disabled={busy}
            >
              연습 시작!
            </button>
          )}
          {rec.status === 'ADOPTED' && rec.started_at && (
            <>
              <button
                type="button"
                className={styles.textButton}
                onClick={() => run(() => setRecommendationCompleted(rec.id, rec.version, true))}
                disabled={busy}
              >
                과제 끝냈어요
              </button>
              <button
                type="button"
                className={styles.pill}
                onClick={() => navigate(`/artworks/new?recommendation=${rec.id}`)}
              >
                이 과제로 그림 기록하기
              </button>
            </>
          )}
          {rec.status === 'COMPLETED' && (
            <button
              type="button"
              className={styles.textButton}
              onClick={() => run(() => setRecommendationCompleted(rec.id, rec.version, false))}
              disabled={busy}
            >
              끝냄 취소
            </button>
          )}
        </div>
      </main>
    </>
  )
}

/** 수행 작품 목록 + 후속 분석 (완료 ≠ 향상) */
function PracticeProgress({ rec, busy, onRun, onReload }) {
  const loadArtworks = useCallback(() => listLinkedArtworks(rec.id), [rec.id])
  const loadFollowUp = useCallback(() => getFollowUp(rec.id), [rec.id])
  const { data: artworks, reload: reloadArtworks } = useAsync(loadArtworks)
  const { data: followUp } = useAsync(loadFollowUp)

  function handleUnlink(artworkId) {
    if (!window.confirm('이 작품을 과제에서 뺄까요? 작품은 지워지지 않아요.')) return
    onRun(async () => {
      await unlinkArtwork(rec.id, artworkId)
      reloadArtworks()
      onReload()
    })
  }

  return (
    <>
      <section className={styles.block}>
        <h2 className={styles.blockTitle}>이 과제로 그린 그림</h2>
        {artworks?.length ? (
          <ul className={styles.works}>
            {artworks.map((a) => (
              <li key={a.artwork_id} className={styles.work}>
                <Link to={`/artworks/${a.artwork_id}`} className={styles.workText}>
                  <span className={styles.workTitle}>{a.title}</span>
                  <span className={styles.source}>
                    {formatMonthDay(a.work_date)} · 첨삭 {a.feedback_count}개
                  </span>
                </Link>
                <button
                  type="button"
                  className={styles.unlink}
                  onClick={() => handleUnlink(a.artwork_id)}
                  disabled={busy}
                >
                  빼기
                </button>
                <ChevronRight size={16} aria-hidden className={styles.workGo} />
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>아직 없어요. 이 과제로 그린 그림을 기록해 보세요.</p>
        )}
      </section>

      {followUp && (
        <section className={styles.block}>
          <h2 className={styles.blockTitle}>
            <ClipboardCheck size={15} aria-hidden /> 그다음 첨삭은 어땠을까?
          </h2>
          <p className={styles.followUp}>{FOLLOW_UP_LABELS[followUp.status] ?? followUp.status}</p>
          {followUp.evidence?.slice(0, 3).map((e) => (
            <Link key={e.item_id} to={`/feedbacks/${e.feedback_id}`} className={styles.followQuote}>
              “{e.content}”
              {e.artwork_title && (
                <span className={styles.source}>
                  {' '}
                  {e.artwork_title}
                  {e.work_date && ` · ${formatMonthDay(e.work_date)}`}
                </span>
              )}
            </Link>
          ))}
          <Notes notes={followUp.notes} />
        </section>
      )}
    </>
  )
}

import { useCallback, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Badge, Button, Card } from '../../../components/ui'
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
import EvidenceList from '../components/EvidenceList'
import Notes from '../components/Notes'
import { DIFFICULTY_LABELS, FOLLOW_UP_LABELS, RECOMMENDATION_STATUS } from '../labels'
import styles from './GrowthPage.module.css'

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

  return (
    <>
      <TopBar
        title="연습 과제"
        belowHeader
        right={<Badge>{RECOMMENDATION_STATUS[rec.status] ?? rec.status}</Badge>}
      />
      <main className={styles.body}>
        <div className={styles.section}>
          <span className={styles.label}>
            {options
              ? labelOf(options.weakness_categories, rec.weakness_category)
              : rec.weakness_category}{' '}
            연습
            {rec.source === 'AI' && ' · AI 추천'}
          </span>
          <h1 className={styles.heading}>{rec.title}</h1>
          <p className={styles.caption}>
            약 {rec.estimated_minutes}분 · {DIFFICULTY_LABELS[rec.difficulty]}
          </p>
          <p>{rec.description}</p>
        </div>

        {rec.method_steps?.length > 0 && (
          <section className={styles.section}>
            <h2 className={styles.label}>연습 방법</h2>
            <ol className={styles.steps}>
              {rec.method_steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </section>
        )}

        <section className={styles.section}>
          <h2 className={styles.label}>추천 이유</h2>
          <p className={styles.caption}>{rec.reason}</p>
          <EvidenceList evidence={rec.evidence} />
        </section>

        {inProgress && <PracticeProgress rec={rec} busy={busy} onRun={run} onReload={reload} />}

        {actionError && <p className={styles.error}>{actionError}</p>}

        <div className={styles.actions}>
          {['DRAFT', 'IN_REVIEW'].includes(rec.status) && (
            <>
              <Button
                onClick={() => run(() => adoptRecommendation(rec.id, rec.version))}
                disabled={busy}
              >
                이 과제 해 보기
              </Button>
              <Button variant="soft" onClick={handleReject} disabled={busy}>
                이번엔 넘어가기
              </Button>
            </>
          )}
          {rec.status === 'ADOPTED' && !rec.started_at && (
            <Button
              onClick={() => run(() => startRecommendation(rec.id, rec.version))}
              disabled={busy}
            >
              연습 시작하기
            </Button>
          )}
          {rec.status === 'ADOPTED' && rec.started_at && (
            <>
              <Button onClick={() => navigate(`/artworks/new?recommendation=${rec.id}`)}>
                이 과제로 작품 기록하기
              </Button>
              <Button
                variant="soft"
                onClick={() => run(() => setRecommendationCompleted(rec.id, rec.version, true))}
                disabled={busy}
              >
                과제 완료하기
              </Button>
            </>
          )}
          {rec.status === 'COMPLETED' && (
            <Button
              variant="soft"
              onClick={() => run(() => setRecommendationCompleted(rec.id, rec.version, false))}
              disabled={busy}
            >
              완료 취소
            </Button>
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
      <section className={styles.section}>
        <h2 className={styles.label}>이 과제로 그린 작품</h2>
        {artworks?.length ? (
          <ul className={styles.list}>
            {artworks.map((a) => (
              <li key={a.artwork_id}>
                <Card className={styles.row}>
                  <Link to={`/artworks/${a.artwork_id}`} className={styles.rowText}>
                    <span className={styles.rowTitle}>{a.title}</span>
                    <span className={styles.caption}>
                      {formatMonthDay(a.work_date)} · 확정 첨삭 {a.feedback_count}개
                    </span>
                  </Link>
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() => handleUnlink(a.artwork_id)}
                    disabled={busy}
                  >
                    빼기
                  </button>
                </Card>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.caption}>아직 없어요. 과제를 연습한 작품을 기록해 보세요.</p>
        )}
      </section>

      {followUp && (
        <section className={styles.section}>
          <h2 className={styles.label}>
            <Sparkles size={14} aria-hidden /> 후속 첨삭 확인
          </h2>
          <Card variant="soft">{FOLLOW_UP_LABELS[followUp.status] ?? followUp.status}</Card>
          <EvidenceList evidence={followUp.evidence} />
          <Notes notes={followUp.notes} />
        </section>
      )}
    </>
  )
}

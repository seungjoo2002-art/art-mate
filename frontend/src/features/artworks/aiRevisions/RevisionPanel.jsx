import { useCallback, useEffect, useMemo, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Button, Checkbox } from '../../../components/ui'
import { usePolling } from '../../../hooks/usePolling'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createRevision, getRevision, getRevisionCandidates, retryRevision } from './api'
import { hasImage, isPending, quotaText, statusText } from './revisionView'
import styles from './RevisionPanel.module.css'

const POLL_MS = 4000
const BLOCKED = {
  TEEN_NOT_ENABLED: '만 18세 미만 학생의 AI 수정본은 아직 준비 중이에요.',
  UNDER_14_BLOCKED: '만 14세 미만은 아직 AI 수정본을 쓸 수 없어요.',
  GUARDIAN_PENDING: '보호자 확인을 기다리고 있어요. 보호자가 확인하면 만들 수 있어요.',
}

/**
 * 단계별 피드백 화면 (v1.3): 지금 사진의 'AI 수정에 반영할 개선사항' + '✨ 피드백 반영 수정하기'.
 * 개선사항은 기존 AI 첨삭 정리(부족한 점·수정 방법)에서 서버가 모은 것 (이 사진 피드백만).
 * 사진을 넘기면 photo가 바뀌어 개선사항·버튼 상태도 그 사진 것으로 바뀐다 (사진마다 key로 새로 그림).
 * 생성은 서버 작업이라 화면을 나가도 계속되고, 돌아오면 최근 수정본 상태를 다시 보여 준다.
 */
export default function RevisionPanel({ artworkId, stageId, photo, feedbackKey }) {
  const navigate = useNavigate()
  const location = useLocation()
  const photoId = photo?.id
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [tick, setTick] = useState(0)
  const [selected, setSelected] = useState(null) // Set (null = 전부, 불러온 직후)
  const [latest, setLatest] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!photoId) return undefined
    let cancelled = false
    getRevisionCandidates(artworkId, photoId).then(
      (result) => {
        if (cancelled) return
        setLoadError('')
        setData(result)
        setLatest(result.latest)
      },
      (error) => !cancelled && setLoadError(toErrorMessage(error)),
    )
    return () => {
      cancelled = true
    }
  }, [artworkId, photoId, feedbackKey, tick])

  const refresh = useCallback(async () => {
    if (!latest) return
    try {
      setLatest(await getRevision(latest.id))
    } catch {
      // 다음 확인 때 다시
    }
  }, [latest])
  usePolling(isPending(latest), POLL_MS, refresh, [latest?.status])

  const candidates = useMemo(() => data?.candidates ?? [], [data])
  const chosen = useMemo(
    () => (selected === null ? new Set(candidates.map((c) => c.key)) : selected),
    [selected, candidates],
  )

  if (!photo || (!data && !loadError)) return null
  if (loadError) {
    return (
      <p className={styles.error}>
        AI 수정 정보를 불러오지 못했어요. {loadError}{' '}
        <button type="button" className={styles.linkButton} onClick={() => setTick((t) => t + 1)}>
          다시 시도
        </button>
      </p>
    )
  }
  const enabled = data.feature_status === 'ENABLED'
  if (!enabled && data.revision_count === 0) return null

  const viewPath = (revisionId) =>
    `/artworks/${artworkId}/stages/${stageId}/ai-revisions?photo=${photoId}${
      revisionId ? `&revision=${revisionId}` : ''
    }`

  function toggle(key, on) {
    const next = new Set(chosen)
    if (on) next.add(key)
    else next.delete(key)
    setSelected(next)
  }

  function goConsent() {
    navigate('/ai-consent?purpose=VISUAL_CRITIQUE', {
      state: { from: `${location.pathname}${location.search}` },
    })
  }

  async function run(action) {
    if (busy) return
    setBusy(true)
    setMessage('')
    try {
      const revision = await action()
      setLatest(revision)
      if (hasImage(revision) || revision.status === 'STORING') {
        setMessage('같은 사진·개선사항으로 만든 수정본이 이미 있어요.')
      }
      setTick((t) => t + 1)
    } catch (error) {
      if (error.code === 'AI_CONSENT_REQUIRED') {
        goConsent()
        return
      }
      if (error.code === 'AI_REVISION_CANDIDATES_CHANGED') {
        setSelected(null)
        setTick((t) => t + 1)
      }
      setMessage(toErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const keys = candidates.filter((c) => chosen.has(c.key)).map((c) => c.key)
  const pending = isPending(latest)
  const status = latest && !hasImage(latest) ? statusText(latest) : null
  const consentBlocked = !data.consent_valid && BLOCKED[data.consent_reason]
  const limit = quotaText(data.quota)
  const canCreate =
    enabled && keys.length > 0 && !busy && !pending && data.quota.can_create && !consentBlocked

  return (
    <section className={styles.panel} aria-label="AI 수정에 반영할 개선사항">
      <h3 className={styles.title}>
        <Sparkles size={16} aria-hidden />
        AI 수정에 반영할 개선사항
      </h3>

      {data.feedback_count === 0 ? (
        <p className={styles.caption}>
          이 사진에 연결된 피드백이 없어요. 피드백을 남기고 AI 첨삭 정리를 하면 수정 예시를 만들 수
          있어요.
        </p>
      ) : candidates.length === 0 ? (
        <p className={styles.caption}>
          {data.unsummarized_count > 0
            ? `이 사진 피드백 ${data.unsummarized_count}개를 먼저 'AI로 정리하기'로 정리해 주세요. 정리된 부족한 점·수정 방법으로 수정 예시를 만들어요.`
            : 'AI 첨삭 정리에서 그림으로 반영할 개선사항을 찾지 못했어요.'}
        </p>
      ) : (
        <>
          <ul className={styles.list}>
            {candidates.map((c) => (
              <li key={c.key}>
                <Checkbox
                  checked={chosen.has(c.key)}
                  onChange={(on) => toggle(c.key, on)}
                  disabled={!enabled || busy || pending}
                  className={styles.check}
                >
                  <span className={styles.tag}>
                    {c.category_label} · {c.kind_label}
                  </span>
                  <span className={styles.text}>{c.text}</span>
                </Checkbox>
              </li>
            ))}
          </ul>
          {data.unsummarized_count > 0 && (
            <p className={styles.caption}>
              아직 AI 정리를 하지 않은 피드백 {data.unsummarized_count}개는 반영되지 않아요.
            </p>
          )}
        </>
      )}

      {status && (
        <div className={`${styles.status} ${pending ? '' : styles.statusFail}`} aria-live="polite">
          <strong>{status.title}</strong>
          <span>{status.sub}</span>
          {latest.retryable && enabled && (
            <button
              type="button"
              className={styles.linkButton}
              onClick={() => run(() => retryRevision(latest.id))}
              disabled={busy || !data.quota.can_create}
            >
              다시 만들기
            </button>
          )}
        </div>
      )}
      {latest && hasImage(latest) && (
        <div className={styles.done} aria-live="polite">
          <strong>AI 수정본이 준비됐어요.</strong>
          <Link to={viewPath(latest.id)} className={styles.compareLink}>
            원본과 비교해 보기
          </Link>
        </div>
      )}

      {enabled && candidates.length > 0 && (
        <>
          {consentBlocked ? (
            <p className={styles.caption}>{consentBlocked}</p>
          ) : (
            !data.consent_valid && (
              <p className={styles.caption}>
                AI 수정본을 만들려면 작품 사진을 외부 AI로 보내는 데 동의가 필요해요.
              </p>
            )
          )}
          <Button
            size="md"
            onClick={() =>
              data.consent_valid ? run(() => createRevision(artworkId, photoId, keys)) : goConsent()
            }
            disabled={!canCreate}
          >
            <Sparkles size={18} aria-hidden />
            {busy ? '요청하는 중…' : pending ? '만드는 중…' : '피드백 반영 수정하기'}
          </Button>
          {limit && <p className={styles.caption}>{limit}</p>}
          <p className={styles.notice}>
            선택한 작품 사진과 개선사항이 외부 AI(OpenAI)로 전달돼요. 만들어진 이미지는 학습용 참고
            예시이며 실제 작품이나 실력 평가가 아니에요.
          </p>
        </>
      )}
      {message && <p className={styles.message}>{message}</p>}

      {data.revision_count > 0 && (
        <Link to={viewPath(null)} className={styles.history}>
          기존 수정본 보기 ({data.revision_count}개)
        </Link>
      )}
    </section>
  )
}

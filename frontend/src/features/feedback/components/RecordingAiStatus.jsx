import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, FileText, Sparkles, Type } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  getAiConsentCached,
  getAiFeatures,
  getSummaryStatus,
  getTranscriptionStatus,
  regenerateSummary,
  retryTranscription,
} from '../aiApi'
import { pollDelay, recordingCardState } from '../aiStatus'
import { BLOCKED_REASONS, consentReasonMessage } from '../consentCopy'
import { processingPath } from '../processingFlow'
import styles from './RecordingAiStatus.module.css'

const MAX_POLLS = 300 // 5초 간격 기준 약 25분
const POLL_PHASE = {
  serverQueued: 'transcribing',
  serverRunning: 'transcribing',
  summarizing: 'summarizing',
}

async function loadStatus(artworkId, recordingId) {
  const [transcription, summary] = await Promise.all([
    getTranscriptionStatus(artworkId, recordingId),
    getSummaryStatus(artworkId, recordingId).catch(() => null), // 전사 전이면 없을 수 있음
  ])
  return { transcription, summary }
}

/**
 * 녹음 카드 아래: 글로 변환하기 / AI로 정리하기 → (진행 화면) → 대본 보기 · AI 첨삭 정리 보기
 * 버튼을 누르면 진행 화면이 필요한 서버 요청(전사 → 정리)을 알아서 보낸다 (중간 단계 버튼 없음).
 * 서버 작업 상태는 이 카드에서도 주기적으로 확인한다 (화면을 나갔다 와도 이어짐).
 */
export default function RecordingAiStatus({ artworkId, recording }) {
  const navigate = useNavigate()
  const location = useLocation()
  const audioGone = recording.audio_available === false
  const load = useCallback(() => loadStatus(artworkId, recording.id), [artworkId, recording.id])
  const { data, reload } = useAsync(load)
  const [features, setFeatures] = useState(null)
  const [consent, setConsent] = useState(null) // AI 첨삭 요약 동의 (null = 아직 모름)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [polls, setPolls] = useState(0)

  useEffect(() => {
    let alive = true
    getAiFeatures().then((value) => alive && setFeatures(value))
    getAiConsentCached().then((value) => alive && setConsent(value))
    return () => {
      alive = false
    }
  }, [])

  // 기기 변환은 쓰지 않는다 (서버 faster-whisper: 미술 용어 힌트·AI 문맥 보정)
  const card = data
    ? recordingCardState({
        transcription: data.transcription,
        summary: data.summary,
        features,
        devicePhase: null,
        interrupted: null,
      })
    : null
  const delay =
    card && POLL_PHASE[card.kind]
      ? pollDelay({ phase: POLL_PHASE[card.kind], retrying: card.retrying })
      : null
  const pollingStopped = delay !== null && polls >= MAX_POLLS

  // 진행 중이면 일정 간격으로 다시 확인. 화면이 안 보이면 다시 보일 때까지 기다림
  useEffect(() => {
    if (delay === null || pollingStopped) return
    const tick = () => {
      if (document.visibilityState !== 'visible') {
        document.addEventListener('visibilitychange', tick, { once: true })
        return
      }
      setPolls((n) => n + 1)
      reload()
    }
    const id = setTimeout(tick, delay)
    return () => {
      clearTimeout(id)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [delay, pollingStopped, data, reload])

  const go = (goal) => navigate(processingPath(artworkId, recording.id, goal))

  /** 실패한 작업 다시 요청 → 진행 화면으로 */
  async function retry(stage) {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      if (stage === 'summary') await regenerateSummary(artworkId, recording.id)
      else await retryTranscription(artworkId, recording.id)
      go(stage === 'summary' ? 'summary' : 'transcript')
    } catch (err) {
      console.warn('[recording-card] retry failed', { code: err?.code ?? null, stage })
      setError(err)
      reload()
    } finally {
      setBusy(false)
    }
  }

  if (!card) return null
  if (audioGone && card.kind === 'idle') return null

  const transcriptPath = `/artworks/${artworkId}/recordings/${recording.id}/transcript`
  const notePath = `/artworks/${artworkId}/notes/new`
  const notStarted = card.kind === 'idle' || card.kind === 'serverDeferred'
  const serverOff = features?.server_transcription === false
  const working = ['serverQueued', 'serverRunning', 'summarizing'].includes(card.kind)

  return (
    <div className={styles.status}>
      {notStarted && !serverOff && (
        <>
          {card.aiAvailable && (
            <button type="button" className={styles.action} onClick={() => go('summary')}>
              <Sparkles size={18} aria-hidden />
              AI로 정리하기
            </button>
          )}
          <button type="button" className={styles.action} onClick={() => go('transcript')}>
            <Type size={18} aria-hidden />
            글로 변환하기
          </button>
        </>
      )}

      {notStarted && serverOff && !card.hasTranscript && (
        <div className={styles.notice}>
          <p>지금은 서버 음성 변환을 쓸 수 없어요. 녹음은 그대로 저장되어 있어요.</p>
          <Link to={notePath} className={styles.link}>
            들은 내용을 글 첨삭으로 남기기
          </Link>
        </div>
      )}

      {working && (
        <div className={styles.progressBox}>
          <p className={styles.progress} role="status">
            <span className={styles.spinner} aria-hidden />
            {card.retrying
              ? '다시 시도하고 있어요…'
              : card.kind === 'summarizing'
                ? '첨삭을 정리하고 있어요…'
                : '글로 바꾸고 있어요…'}
          </p>
          <p className={styles.hint}>
            {card.delayed || pollingStopped
              ? '평소보다 오래 걸리고 있어요. 서버에서 계속 처리하고 있어요. '
              : ''}
            <Link
              to={processingPath(
                artworkId,
                recording.id,
                card.kind === 'summarizing' ? 'summary' : 'transcript',
              )}
              className={styles.link}
            >
              진행 상황 보기
            </Link>
          </p>
        </div>
      )}

      {card.kind === 'failed' && (
        <div className={styles.failed}>
          <span>{card.message}</span>
          {card.retry && (
            <button
              type="button"
              className={styles.link}
              onClick={() => retry(card.retry)}
              disabled={busy}
            >
              {busy ? '다시 요청하는 중…' : '다시 시도'}
            </button>
          )}
        </div>
      )}

      {card.hasTranscript && (
        <Link to={transcriptPath} className={styles.result}>
          <FileText size={18} aria-hidden />
          <span className={styles.resultText}>녹음 대본 보기</span>
          <ChevronRight size={18} aria-hidden />
        </Link>
      )}

      {card.kind === 'transcribed' && card.aiAvailable && consent?.is_valid === false && (
        <div className={styles.notice}>
          <p>
            {consentReasonMessage(consent.reason) ??
              'AI 첨삭 정리를 하려면 AI 사용 동의가 필요해요. 동의하지 않아도 대본은 볼 수 있어요.'}
          </p>
          {!BLOCKED_REASONS.includes(consent.reason) && (
            <button
              type="button"
              className={styles.link}
              onClick={() => navigate('/ai-consent', { state: { from: location.pathname } })}
            >
              {consent.reason === 'GUARDIAN_PENDING' ? '보호자 확인 링크 보기' : 'AI 사용 동의 확인하기'}
            </button>
          )}
        </div>
      )}
      {card.kind === 'transcribed' && card.aiAvailable && consent?.is_valid !== false && (
        <button type="button" className={styles.action} onClick={() => go('summary')}>
          <Sparkles size={18} aria-hidden />
          AI로 정리하기
        </button>
      )}
      {card.hasTranscript && !card.aiAvailable && (
        <p className={styles.muted}>
          {features?.ai_summary_status === 'TERMS_UNCONFIRMED'
            ? 'AI 서비스 설정이 필요해요 (외부 AI 이용 조건 확인 중). 대본을 보고 직접 정리할 수 있어요.'
            : 'AI 서비스 설정이 필요해요. 대본을 보고 직접 정리할 수 있어요.'}
        </p>
      )}

      {card.kind === 'ready' && (
        <Link to={`/feedbacks/${card.feedbackId}`} className={styles.result}>
          <Sparkles size={18} aria-hidden />
          <span className={styles.resultText}>AI 첨삭 정리 보기</span>
          <span className={card.feedbackStatus === 'APPROVED' ? styles.done : styles.todo}>
            {card.feedbackStatus === 'APPROVED' ? '확정됨' : '확인 필요'}
          </span>
          <ChevronRight size={18} aria-hidden />
        </Link>
      )}

      {error && <p className={styles.error}>{toErrorMessage(error)}</p>}
    </div>
  )
}

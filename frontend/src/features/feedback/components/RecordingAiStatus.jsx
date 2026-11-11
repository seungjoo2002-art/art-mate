import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, Sparkles } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  getSummaryStatus,
  getTranscriptionStatus,
  regenerateSummary,
  requestSummary,
  retryTranscription,
  startAiSummary,
} from '../aiApi'
import { aiPhase, pollDelay } from '../aiStatus'
import styles from './RecordingAiStatus.module.css'

const MAX_POLLS = 300 // 5초 간격 기준 약 25분 (문서 권장: 30분쯤에서 멈춤)
const NOT_CONFIGURED = ['STT_NOT_CONFIGURED', 'AI_NOT_CONFIGURED']

async function loadStatus(artworkId, recordingId) {
  const [transcription, summary] = await Promise.all([
    getTranscriptionStatus(artworkId, recordingId),
    getSummaryStatus(artworkId, recordingId).catch(() => null), // 전사 전이면 없을 수 있음
  ])
  return { transcription, summary }
}

/** 녹음 카드 아래: AI 정리 버튼 → 진행 상태 → 결과 보기 */
export default function RecordingAiStatus({ artworkId, recording }) {
  const navigate = useNavigate()
  const location = useLocation()
  const load = useCallback(() => loadStatus(artworkId, recording.id), [artworkId, recording.id])
  const { data, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [polls, setPolls] = useState(0)

  const state = data ? aiPhase(data.transcription, data.summary) : null
  const delay = state ? pollDelay(state) : null
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

  async function run(action) {
    setBusy(true)
    setError(null)
    try {
      await action()
      setPolls(0)
      reload()
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

  async function startAi() {
    const { needsConsent } = await startAiSummary(artworkId, recording.id)
    if (needsConsent) navigate('/ai-consent', { state: { from: location.pathname } })
  }

  function retry() {
    if (state.retry === 'transcription')
      return run(() => retryTranscription(artworkId, recording.id))
    return run(() => regenerateSummary(artworkId, recording.id))
  }

  if (!state) return null
  if (recording.audio_available === false && state.phase === 'idle') return null

  if (error && NOT_CONFIGURED.includes(error.code)) {
    return <p className={styles.muted}>{toErrorMessage(error)}</p>
  }

  return (
    <div className={styles.status}>
      {state.phase === 'idle' && (
        <button
          type="button"
          className={styles.action}
          onClick={() => run(startAi)}
          disabled={busy}
        >
          <Sparkles size={18} aria-hidden />
          {busy ? '요청하는 중…' : 'AI로 피드백 정리하기'}
        </button>
      )}

      {state.phase === 'needsSummary' && (
        <button
          type="button"
          className={styles.action}
          onClick={() => run(() => requestSummary(artworkId, recording.id))}
          disabled={busy}
        >
          <Sparkles size={18} aria-hidden />
          {busy ? '요청하는 중…' : 'AI 요약 만들기'}
        </button>
      )}

      {(state.phase === 'transcribing' || state.phase === 'summarizing') && (
        <p className={styles.progress} role="status">
          <span className={styles.spinner} aria-hidden />
          {state.retrying
            ? '다시 시도하는 중…'
            : state.phase === 'transcribing'
              ? '녹음을 글로 바꾸는 중… (몇 분 걸릴 수 있어요)'
              : 'AI가 정리하는 중…'}
          {pollingStopped && (
            <button
              type="button"
              className={styles.link}
              onClick={() => {
                setPolls(0)
                reload()
              }}
            >
              새로고침
            </button>
          )}
        </p>
      )}

      {state.phase === 'failed' && (
        <div className={styles.failed}>
          <span>{state.message}</span>
          {state.retry && (
            <button type="button" className={styles.link} onClick={retry} disabled={busy}>
              다시 시도
            </button>
          )}
        </div>
      )}

      {state.phase === 'ready' && (
        <Link to={`/feedbacks/${state.feedbackId}`} className={styles.result}>
          <Sparkles size={18} aria-hidden />
          <span className={styles.resultText}>AI 정리 결과 보기</span>
          <span className={state.feedbackStatus === 'APPROVED' ? styles.done : styles.todo}>
            {state.feedbackStatus === 'APPROVED' ? '확정됨' : '확인 필요'}
          </span>
          <ChevronRight size={18} aria-hidden />
        </Link>
      )}

      {data.transcription?.transcription_status === 'COMPLETED' && (
        <Link
          to={`/artworks/${artworkId}/recordings/${recording.id}/transcript`}
          className={styles.link}
        >
          녹음 원문 보기
        </Link>
      )}
      {error && <p className={styles.error}>{toErrorMessage(error)}</p>}
    </div>
  )
}

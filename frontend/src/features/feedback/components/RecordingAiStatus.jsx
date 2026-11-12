import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, FileText, Sparkles, Type } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getRecordingUrl } from '../api'
import {
  getAiConsent,
  getAiFeatures,
  getSummaryStatus,
  getTranscriptionStatus,
  regenerateSummary,
  requestSummary,
  requestTranscription,
  retryTranscription,
} from '../aiApi'
import { pollDelay, recordingCardState } from '../aiStatus'
import { resolvePlan } from '../stt/browserStt'
import { forgetInterrupted, getInterrupted, skipToServer, startDeviceJob } from '../stt/deviceJobs'
import { useDeviceJob } from '../stt/useBrowserStt'
import BrowserSttStatus from './BrowserSttStatus'
import styles from './RecordingAiStatus.module.css'

const MAX_POLLS = 300 // 5초 간격 기준 약 25분 (문서 권장: 30분쯤에서 멈춤)
const POLL_PHASE = { serverQueued: 'transcribing', serverRunning: 'transcribing', summarizing: 'summarizing' }
// 기기 작업이 끝나면(저장·서버 요청·실패) 서버 상태를 다시 읽는다
const DEVICE_SETTLED = ['done', 'server', 'failed']

const timeOf = (iso) =>
  new Date(iso).toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' })

// 이 카드에서만 쓰는 안내 (요청 결과에 따라 문구를 구체적으로)
const CARD_MESSAGES = {
  RATE_LIMITED: '오늘 AI 정리 요청을 모두 사용했어요. 내일 다시 이용해 주세요. 녹음 대본은 지금도 볼 수 있어요.',
  AI_NOT_CONFIGURED: 'AI 정리 기능이 아직 열리지 않았어요. 녹음 대본은 지금도 볼 수 있어요.',
}

async function loadStatus(artworkId, recordingId) {
  const [transcription, summary] = await Promise.all([
    getTranscriptionStatus(artworkId, recordingId),
    getSummaryStatus(artworkId, recordingId).catch(() => null), // 전사 전이면 없을 수 있음
  ])
  return { transcription, summary }
}

function cardMessage(error) {
  return CARD_MESSAGES[error?.code] ?? toErrorMessage(error)
}

/**
 * 녹음 카드 아래: 녹음을 글로 바꾸기 → 대본 보기 → (원할 때만) AI로 피드백 정리하기 → 결과 보기
 * 어떤 기능이 꺼져 있어도 카드 전체를 가리지 않고, 쓸 수 있는 기능(대본 보기·글 첨삭)은 계속 보여 준다
 */
export default function RecordingAiStatus({ artworkId, recording }) {
  const navigate = useNavigate()
  const location = useLocation()
  const audioGone = recording.audio_available === false
  const load = useCallback(() => loadStatus(artworkId, recording.id), [artworkId, recording.id])
  const { data, reload } = useAsync(load)
  const [features, setFeatures] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null) // 서버 변환을 쓸 수 없을 때 안내
  const [polls, setPolls] = useState(0)
  const device = useDeviceJob(recording.id) // 화면을 옮겨도 유지되는 기기 변환 상태
  const interrupted = getInterrupted(recording.id)
  const devicePhase = device?.phase ?? null

  useEffect(() => {
    if (DEVICE_SETTLED.includes(devicePhase)) reload()
  }, [devicePhase, reload])

  useEffect(() => {
    let alive = true
    getAiFeatures().then((value) => alive && setFeatures(value))
    return () => {
      alive = false
    }
  }, [])

  const card = data
    ? recordingCardState({
        transcription: data.transcription,
        summary: data.summary,
        features,
        devicePhase,
        interrupted,
      })
    : null
  const delay = card && POLL_PHASE[card.kind] ? pollDelay({ phase: POLL_PHASE[card.kind], retrying: card.retrying }) : null
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
      if (err.code === 'STT_NOT_CONFIGURED') {
        setNotice('server')
        return
      }
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  /**
   * 이 기기에서 글로 바꾸기 (저장된 녹음을 다시 받아 변환). 기기에서 못 하면 false.
   * 변환은 앱 전역 작업이라 다른 화면으로 가도 계속되고, 돌아오면 진행 상태가 보인다
   */
  async function transcribeOnDevice() {
    if (audioGone) return false
    const plan = await resolvePlan()
    if (!plan) return false
    startDeviceJob({
      artworkId,
      recordingId: recording.id,
      getBlob: async () => {
        const { url } = await getRecordingUrl(artworkId, recording.id)
        const response = await fetch(url)
        if (!response.ok) throw new Error('download failed')
        return response.blob()
      },
    })
    return true
  }

  /** 서버 변환 요청 (대기 중인 백업 작업이 있으면 지금 처리하도록 앞당김) */
  async function transcribeOnServer() {
    setNotice(null)
    if (features?.server_transcription === false) {
      setNotice('server')
      return
    }
    try {
      await requestTranscription(artworkId, recording.id, { autoSummarize: false })
    } catch (err) {
      if (err.code !== 'TRANSCRIPTION_ALREADY_DONE') throw err
    }
  }

  /** "녹음을 글로 바꾸기": AI 동의 없이 가능 (기기 우선, 안 되면 서버) */
  async function transcribe() {
    setNotice(null)
    if (await transcribeOnDevice()) return
    await transcribeOnServer()
  }

  /** "AI로 피드백 정리하기": 사용자가 누를 때만, AI 전송 동의 확인 후 */
  async function summarize({ regenerate = false } = {}) {
    const consent = await getAiConsent()
    if (!consent.is_valid) {
      navigate('/ai-consent', { state: { from: location.pathname } })
      return
    }
    if (regenerate) await regenerateSummary(artworkId, recording.id)
    else await requestSummary(artworkId, recording.id)
  }

  if (!card) return null
  if (audioGone && card.kind === 'idle') return null

  const transcriptPath = `/artworks/${artworkId}/recordings/${recording.id}/transcript`
  const notePath = `/artworks/${artworkId}/notes/new`
  const canSummarize = ['transcribed', 'failed'].includes(card.kind) && card.hasTranscript

  return (
    <div className={styles.status}>
      {card.kind === 'deviceTranscribing' && (
        <BrowserSttStatus state={device} onSkip={() => skipToServer(recording.id)} afterSave />
      )}

      {card.kind === 'interrupted' && (
        <div className={styles.notice} role="status">
          <p>
            {card.interrupted.crashed
              ? '이 기기의 메모리가 부족해 변환이 중단된 것 같아요.'
              : '글로 바꾸는 도중에 화면이 닫혔어요.'}{' '}
            녹음은 그대로 저장되어 있어요.
            {card.interrupted.done > 0 && card.interrupted.total
              ? ` (${card.interrupted.done}/${card.interrupted.total} 구간 변환됨)`
              : ''}
          </p>
          {card.deferredUntil && (
            <p className={styles.hint}>그대로 두면 {timeOf(card.deferredUntil)} 이후 서버가 이어서 변환해요.</p>
          )}
          <button
            type="button"
            className={styles.action}
            onClick={() => run(transcribeOnDevice)}
            disabled={busy || audioGone}
          >
            <Type size={18} aria-hidden />
            {card.interrupted.done > 0 ? '이 기기에서 이어서 바꾸기' : '이 기기에서 다시 바꾸기'}
          </button>
          {card.serverAvailable && (
            <button
              type="button"
              className={styles.link}
              onClick={() =>
                run(async () => {
                  forgetInterrupted(recording.id)
                  await transcribeOnServer()
                })
              }
              disabled={busy}
            >
              서버에서 변환하기
            </button>
          )}
        </div>
      )}

      {card.kind === 'serverDeferred' && (
        <div className={styles.progressBox}>
          <p className={styles.progress} role="status">
            이 기기 변환이 끝나지 않으면 {timeOf(card.deferredUntil)} 이후 서버가 변환해요.
          </p>
          <p className={styles.hint}>
            <button
              type="button"
              className={styles.link}
              onClick={() => run(transcribeOnDevice)}
              disabled={busy}
            >
              이 기기에서 바꾸기
            </button>{' '}
            <button
              type="button"
              className={styles.link}
              onClick={() => run(transcribeOnServer)}
              disabled={busy}
            >
              지금 서버에서 변환하기
            </button>
          </p>
        </div>
      )}

      {card.kind === 'idle' && (
        <button
          type="button"
          className={styles.action}
          onClick={() => run(transcribe)}
          disabled={busy}
        >
          <Type size={18} aria-hidden />
          {busy ? '준비하는 중…' : '녹음을 글로 바꾸기'}
        </button>
      )}

      {(notice === 'server' || devicePhase === 'failed') && !card.hasTranscript && card.kind === 'idle' && (
        <div className={styles.notice}>
          <p>
            {devicePhase === 'failed'
              ? '이 기기에서 글로 바꾸지 못했고, 서버 변환도 지금은 쓸 수 없어요.'
              : '이 기기에서는 녹음을 바로 글로 바꿀 수 없고, 서버 변환도 지금은 쓸 수 없어요.'}{' '}
            녹음은 그대로 저장되어 있어요.
          </p>
          <Link to={notePath} className={styles.link}>
            들은 내용을 글 첨삭으로 남기기
          </Link>
        </div>
      )}

      {(card.kind === 'serverQueued' || card.kind === 'serverRunning' || card.kind === 'summarizing') && (
        <div className={styles.progressBox}>
          <p className={styles.progress} role="status">
            <span className={styles.spinner} aria-hidden />
            {card.retrying
              ? '다시 시도하는 중…'
              : card.kind === 'serverQueued'
                ? '서버 변환 순서를 기다리는 중…'
                : card.kind === 'serverRunning'
                  ? '서버에서 녹음을 글로 바꾸는 중…'
                  : 'AI가 피드백을 정리하는 중…'}
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
          {card.delayed && card.kind === 'serverQueued' && (
            <p className={styles.hint}>
              서버 처리가 늦어지고 있어요 (서버 사정에 따라 몇 시간 걸릴 수 있어요).{' '}
              <button
                type="button"
                className={styles.link}
                onClick={() => run(transcribeOnDevice)}
                disabled={busy}
              >
                이 기기에서 바로 바꾸기
              </button>
            </p>
          )}
          {card.delayed && card.kind === 'summarizing' && (
            <p className={styles.hint}>
              AI 정리가 예상보다 늦어지고 있어요. 그동안 녹음 대본은 먼저 볼 수 있어요.
            </p>
          )}
        </div>
      )}

      {card.kind === 'failed' && (
        <div className={styles.failed}>
          <span>{card.message}</span>
          {card.retry === 'transcription' && (
            <button
              type="button"
              className={styles.link}
              onClick={() => run(() => retryTranscription(artworkId, recording.id))}
              disabled={busy}
            >
              다시 시도
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

      {canSummarize && card.aiAvailable && (card.kind === 'transcribed' || card.retry === 'summary') && (
        <button
          type="button"
          className={styles.action}
          onClick={() => run(() => summarize({ regenerate: card.kind === 'failed' }))}
          disabled={busy}
        >
          <Sparkles size={18} aria-hidden />
          {busy ? '요청하는 중…' : card.kind === 'failed' ? 'AI 정리 다시 요청하기' : 'AI로 피드백 정리하기'}
        </button>
      )}
      {canSummarize && !card.aiAvailable && (
        <p className={styles.muted}>AI 정리 기능이 아직 열리지 않았어요. 대본을 보고 직접 정리할 수 있어요.</p>
      )}

      {card.kind === 'ready' && (
        <Link to={`/feedbacks/${card.feedbackId}`} className={styles.result}>
          <Sparkles size={18} aria-hidden />
          <span className={styles.resultText}>AI 정리 결과 보기</span>
          <span className={card.feedbackStatus === 'APPROVED' ? styles.done : styles.todo}>
            {card.feedbackStatus === 'APPROVED' ? '확정됨' : '확인 필요'}
          </span>
          <ChevronRight size={18} aria-hidden />
        </Link>
      )}

      {error && <p className={styles.error}>{cardMessage(error)}</p>}
    </div>
  )
}

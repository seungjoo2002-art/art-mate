import { useCallback, useEffect, useRef, useState } from 'react'
import { PencilLine } from 'lucide-react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Button } from '../../../components/ui'
import { usePolling } from '../../../hooks/usePolling'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  getAiConsent,
  getSummaryStatus,
  getTranscriptionStatus,
  regenerateSummary,
  requestSummary,
  requestTranscription,
  retryTranscription,
} from '../aiApi'
import { processingPath, processingState, processingText } from '../processingFlow'
import styles from './RecordingProcessingPage.module.css'

// 서버 요청이 실패했을 때 화면 문구 (그 밖은 공통 오류 문구)
const ACTION_MESSAGES = {
  RATE_LIMITED: '오늘 AI 정리 요청을 모두 사용했어요. 내일 다시 이용해 주세요. 대본은 지금도 볼 수 있어요.',
  AI_NOT_CONFIGURED: 'AI 정리 기능이 아직 설정되지 않았어요. 대본은 지금도 볼 수 있어요.',
  STT_NOT_CONFIGURED: '서버 음성 변환이 아직 설정되지 않았어요. 들은 내용을 직접 글로 적어 주세요.',
  RECORDING_AUDIO_EXPIRED: '보관 기간이 지나 녹음 파일이 삭제됐어요. 직접 글로 적어 주세요.',
  RECORDING_TOO_LONG: '녹음이 너무 길어서 글로 바꿀 수 없어요.',
}

// 보낸 요청이 서버 상태에 이만큼 반영되지 않으면 '다시 시도'를 보여 준다
const STALL_MS = 20_000

function logFailure(where, err) {
  // 원인 확인용 (내용·토큰 없이 코드·요청 ID만)
  console.warn(`[recording-processing] ${where}`, {
    code: err?.code ?? null,
    status: err?.status ?? null,
    requestId: err?.requestId ?? null,
  })
}

async function loadServer(artworkId, recordingId) {
  const [transcription, summary] = await Promise.all([
    getTranscriptionStatus(artworkId, recordingId),
    getSummaryStatus(artworkId, recordingId).catch(() => null), // 전사 전이면 없을 수 있음
  ])
  return { transcription, summary }
}

/**
 * 녹음 처리 진행 화면 (/artworks/:artworkId/recordings/:recordingId/processing?goal=transcript|summary)
 * 버튼 한 번으로: 필요한 서버 요청(전사·AI 정리)을 이 화면이 알아서 보내고, 끝나면 결과 화면으로 이동.
 * 상태는 서버에서 읽으므로 화면을 나갔다 와도 이어지고, 이미 끝난 단계는 다시 요청하지 않는다.
 */
export default function RecordingProcessingPage() {
  const { artworkId, recordingId } = useParams()
  const [params] = useSearchParams()
  const goal = params.get('goal') === 'summary' ? 'summary' : 'transcript'
  const navigate = useNavigate()
  const location = useLocation()
  const here = location.pathname + location.search

  const [server, setServer] = useState(null) // 마지막으로 받은 서버 상태 (연결이 끊겨도 유지)
  const [netError, setNetError] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [tick, setTick] = useState(0)
  // AI 정리 동의가 없음 → 안내 패널 (동의 화면으로 자동 이동하지 않음: 뒤로 가기가 다시 동의 화면으로
  // 튕기는 고리를 막기 위해)
  const [consentGoal, setConsentGoal] = useState(null)
  const needsConsent = consentGoal === goal
  // 이 화면에서 보낸 요청 (key → 끝난 시각). 같은 요청을 다시 보내지 않는다 (중복 요청 방지)
  const attempted = useRef(new Map())
  const [stalledKey, setStalledKey] = useState(null) // 보냈는데 서버에 반영되지 않은 요청

  useEffect(() => {
    let alive = true
    loadServer(artworkId, recordingId).then(
      (value) => {
        if (!alive) return
        setServer(value)
        setNetError(null)
      },
      (err) => {
        if (!alive) return
        logFailure('status', err)
        setNetError(err)
      },
    )
    return () => {
      alive = false
    }
  }, [artworkId, recordingId, tick])

  const refresh = useCallback(() => setTick((n) => n + 1), [])
  const state = server ? processingState({ goal, ...server }) : null
  // 진행 중이면 주기적으로 확인. 연결 오류면 천천히 다시 확인 (실패로 단정하지 않음)
  usePolling(Boolean(state?.poll) || Boolean(netError), state?.poll ?? 10_000, refresh, [server, netError])

  /** 서버 요청 하나 실행 (버튼·자동 공통). key가 같으면 이 화면에서 한 번만 */
  const perform = useCallback(
    async (key, action) => {
      if (attempted.current.has(key)) return
      attempted.current.set(key, null)
      setBusy(true)
      setActionError(null)
      try {
        await action()
        attempted.current.set(key, Date.now())
      } catch (err) {
        if (err?.code === 'AI_CONSENT_REQUIRED') {
          attempted.current.delete(key)
          setConsentGoal(goal)
          return
        }
        logFailure(key, err)
        attempted.current.delete(key) // '다시 시도'로 다시 보낼 수 있게
        setActionError(err)
      } finally {
        setBusy(false)
        refresh()
      }
    },
    [refresh, goal],
  )

  /** AI 정리 전 동의 확인. 없으면 안내 패널 (요청을 보내지 않음) */
  const ensureConsent = useCallback(async () => {
    const consent = await getAiConsent()
    if (consent.is_valid) return true
    setConsentGoal(goal)
    return false
  }, [goal])

  // 필요한 서버 요청을 자동으로 (중간 버튼 없음)
  const step = state?.step
  const feedbackId = state?.feedbackId
  const tJobId = server?.transcription?.job?.id ?? 'none'
  const sJobId = server?.summary?.job?.id ?? 'none'

  const startTranscription = useCallback(async () => {
    if (goal === 'summary' && !(await ensureConsent())) return
    try {
      await requestTranscription(artworkId, recordingId, { autoSummarize: goal === 'summary' })
    } catch (err) {
      if (err?.code !== 'TRANSCRIPTION_ALREADY_DONE') throw err // 이미 끝났으면 다음 단계로
    }
  }, [goal, ensureConsent, artworkId, recordingId])

  const startSummary = useCallback(async () => {
    if (!(await ensureConsent())) return
    try {
      await requestSummary(artworkId, recordingId)
    } catch (err) {
      // 이전 초안이 있는 등 일반 요청이 안 되는 상태 → 새로 정리
      if (err?.code !== 'FEEDBACK_INVALID_STATE') throw err
      await regenerateSummary(artworkId, recordingId)
    }
  }, [ensureConsent, artworkId, recordingId])

  useEffect(() => {
    if (step === 'done') {
      const target =
        goal === 'summary'
          ? `/feedbacks/${feedbackId}`
          : `/artworks/${artworkId}/recordings/${recordingId}/transcript`
      // fromProcessing: 대본 화면이 다시 진행 화면으로 돌려보내는 고리 방지
      navigate(target, { replace: true, state: { fromProcessing: true } })
      return undefined
    }
    if (busy || actionError || needsConsent) return undefined
    let key = null
    let action = null
    if (step === 'startTranscription' || step === 'advance') {
      key = `${goal}:transcribe:${step}:${tJobId}`
      action = startTranscription
    } else if (step === 'startSummary') {
      key = `${goal}:summary:${sJobId}`
      action = startSummary
    }
    if (!action) return undefined
    if (attempted.current.has(key)) {
      // 이미 보냈는데 서버 상태가 그대로면 20초 뒤 '다시 시도' 안내 (끝없이 돌지 않게)
      const sentAt = attempted.current.get(key)
      if (sentAt === null) return undefined
      const id = setTimeout(() => setStalledKey(key), Math.max(0, sentAt + STALL_MS - Date.now()))
      return () => clearTimeout(id)
    }
    // 요청은 효과 밖(다음 틱)에서 시작하고, 화면이 바뀌면 취소 (StrictMode 이중 실행에도 한 번만)
    const id = setTimeout(() => perform(key, action), 0)
    return () => clearTimeout(id)
  }, [
    needsConsent,
    step,
    feedbackId,
    tJobId,
    sJobId,
    busy,
    actionError,
    goal,
    artworkId,
    recordingId,
    perform,
    startTranscription,
    startSummary,
    navigate,
  ])

  function retryFailed() {
    const failedJob = state.stage === 'summary' ? sJobId : tJobId
    perform(`retry:${state.stage}:${failedJob}`, () =>
      state.stage === 'summary'
        ? regenerateSummary(artworkId, recordingId)
        : retryTranscription(artworkId, recordingId),
    )
  }

  function retryAction() {
    setActionError(null) // 자동 요청 효과가 같은 단계를 다시 보낸다
  }

  function retryStalled() {
    attempted.current.delete(stalledKey) // 같은 요청을 한 번 더 보낸다 (서버가 중복은 막아 줌)
    setStalledKey(null)
    refresh()
  }

  const artworkPath = `/artworks/${artworkId}`
  const notePath = `${artworkPath}/notes/new`
  const hasTranscript = server?.transcription?.transcription_status === 'COMPLETED'
  const text = state ? processingText(state, goal) : null
  const failed = step === 'failed'
  // 지금 단계의 요청이 반영되지 않은 채 멈춤 (단계가 바뀌면 자동으로 사라짐)
  const stalled =
    stalledKey !== null &&
    ['startTranscription', 'advance', 'startSummary'].includes(step) &&
    stalledKey.includes(step === 'startSummary' ? 'summary:' : 'transcribe:')

  return (
    <>
      <TopBar title={goal === 'summary' ? 'AI로 정리하기' : '글로 변환하기'} belowHeader />
      <main className={styles.body}>
        {!server && netError ? (
          <section className={styles.panel}>
            <h1 className={styles.title}>상태를 불러오지 못했어요</h1>
            <p className={styles.detail}>
              {toErrorMessage(netError)} 연결되면 자동으로 다시 확인할게요.
            </p>
            <Button onClick={refresh}>다시 확인</Button>
          </section>
        ) : !state ? (
          <section className={styles.panel} aria-busy>
            <span className={styles.spinner} aria-hidden />
            <p className={styles.detail}>상태를 확인하고 있어요…</p>
          </section>
        ) : needsConsent ? (
          <section className={styles.panel}>
            <h1 className={styles.title}>AI 사용 동의가 필요해요</h1>
            <p className={styles.detail}>
              AI로 첨삭을 정리하려면 먼저 동의해 주세요. 동의하지 않아도 녹음을 글로 바꿀 수 있어요.
            </p>
            <Button onClick={() => navigate('/ai-consent', { state: { from: here } })}>
              동의하러 가기
            </Button>
            <Link
              to={processingPath(artworkId, recordingId, 'transcript')}
              replace
              className={styles.inline}
            >
              글로 변환만 하기
            </Link>
          </section>
        ) : stalled ? (
          <section className={styles.panel} role="alert">
            <h1 className={styles.title}>요청이 아직 반영되지 않았어요</h1>
            <p className={styles.detail}>서버 응답이 늦어지고 있어요. 한 번 더 요청해 볼까요?</p>
            <Button onClick={retryStalled} disabled={busy}>
              다시 시도
            </Button>
          </section>
        ) : actionError ? (
          <section className={styles.panel} role="alert">
            <h1 className={styles.title}>요청을 보내지 못했어요</h1>
            <p className={styles.detail}>
              {ACTION_MESSAGES[actionError.code] ?? toErrorMessage(actionError)}
            </p>
            <Button onClick={retryAction} disabled={busy}>
              다시 시도
            </Button>
          </section>
        ) : failed ? (
          <section className={styles.panel} role="alert">
            <h1 className={styles.title}>{text.title}</h1>
            <p className={styles.detail}>{text.detail}</p>
            {state.canRetry && (
              <Button onClick={retryFailed} disabled={busy}>
                {busy ? '다시 요청하는 중…' : '다시 시도'}
              </Button>
            )}
          </section>
        ) : (
          <section className={styles.panel} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden />
            <h1 className={styles.title}>{text.title}</h1>
            {text.detail && <p className={styles.detail}>{text.detail}</p>}
            {state.slow && (
              <p className={styles.slow}>
                평소보다 오래 걸리고 있어요. 이 화면을 나가도 서버에서 계속 처리하고, 작품 화면의
                녹음 카드에서 이어서 볼 수 있어요.
              </p>
            )}
            {netError && (
              <p className={styles.slow}>연결이 불안정해요. 다시 연결되면 이어서 확인할게요.</p>
            )}
          </section>
        )}

        <nav className={styles.links}>
          {hasTranscript && goal === 'summary' && (
            <Link to={`${artworkPath}/recordings/${recordingId}/transcript`}>녹음 대본 보기</Link>
          )}
          {(failed || actionError) && !hasTranscript && (
            <Link to={notePath}>
              <PencilLine size={14} aria-hidden /> 직접 글로 적기
            </Link>
          )}
          <Link to={artworkPath}>작품으로 돌아가기</Link>
        </nav>
      </main>
    </>
  )
}

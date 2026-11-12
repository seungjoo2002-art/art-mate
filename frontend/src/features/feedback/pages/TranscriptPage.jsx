import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, Pause, Play, Sparkles } from 'lucide-react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Textarea } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  getAiConsent,
  getAiFeatures,
  getSummaryStatus,
  getTranscript,
  getTranscriptionStatus,
  regenerateSummary,
  requestSummary,
  updateTranscript,
} from '../aiApi'
import { aiPhase } from '../aiStatus'
import { formatDuration } from '../format'
import { useEvidencePlayer } from '../useEvidencePlayer'
import styles from './TranscriptPage.module.css'

/**
 * 녹음 전사문 보기·수정 (/artworks/:artworkId/recordings/:recordingId/transcript)
 * 수정은 바꾼 문장만 보내고 원본은 서버에 보존됨. 수정하면 AI 정리 초안이 사라져 다시 요청해야 함
 */
export default function TranscriptPage() {
  const { artworkId, recordingId } = useParams()
  const load = useCallback(() => getTranscript(artworkId, recordingId), [artworkId, recordingId])
  const { data: transcript, error, reload } = useAsync(load)

  if (error?.code === 'TRANSCRIPT_NOT_READY') {
    return <TranscriptNotReady artworkId={artworkId} recordingId={recordingId} onReload={reload} />
  }
  if (error) {
    return (
      <FullScreenStatus title="대본을 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!transcript) return <FullScreenStatus />
  return (
    <TranscriptEditor
      key={transcript.id}
      artworkId={artworkId}
      recordingId={recordingId}
      transcript={transcript}
      onSaved={reload}
    />
  )
}

/** 아직 대본이 없을 때: 진행 상태(서버 대기·실패)를 알려 주고 작품 화면으로 돌아가게 함 */
function TranscriptNotReady({ artworkId, recordingId, onReload }) {
  const navigate = useNavigate()
  const [status, setStatus] = useState(null)
  useEffect(() => {
    let alive = true
    getTranscriptionStatus(artworkId, recordingId)
      .then((value) => alive && setStatus(aiPhase(value, null)))
      .catch(() => alive && setStatus({ phase: 'idle' }))
    return () => {
      alive = false
    }
  }, [artworkId, recordingId])
  const description =
    status?.phase === 'transcribing'
      ? '녹음을 글로 바꾸는 중이에요. 끝나면 이 화면에서 대본을 볼 수 있어요.'
      : status?.phase === 'failed'
        ? `${status.message} 작품 화면의 녹음 카드에서 다시 시도할 수 있어요.`
        : '아직 글로 바꾸지 않은 녹음이에요. 작품 화면의 녹음 카드에서 "녹음을 글로 바꾸기"를 눌러 주세요.'
  return (
    <FullScreenStatus title="아직 대본이 없어요" description={description}>
      <Button onClick={() => navigate(`/artworks/${artworkId}`)}>작품으로 돌아가기</Button>
      {status?.phase === 'transcribing' && (
        <Button variant="soft" onClick={onReload}>
          새로고침
        </Button>
      )}
    </FullScreenStatus>
  )
}

/** 대본 아래 AI 정리: 사용자가 누를 때만 요청 (동의 확인), 결과가 있으면 결과 보기 */
function SummaryPanel({ artworkId, recordingId, refreshKey }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [features, setFeatures] = useState(null)
  const [summary, setSummary] = useState(undefined)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let alive = true
    getAiFeatures().then((value) => alive && setFeatures(value))
    getSummaryStatus(artworkId, recordingId)
      .then((value) => alive && setSummary(value))
      .catch(() => alive && setSummary(null))
    return () => {
      alive = false
    }
  }, [artworkId, recordingId, refreshKey])

  if (summary === undefined) return null
  const phase = aiPhase({ transcription_status: 'COMPLETED' }, summary)

  async function handleSummarize() {
    setBusy(true)
    setMessage('')
    try {
      const consent = await getAiConsent()
      if (!consent.is_valid) {
        navigate('/ai-consent', { state: { from: location.pathname } })
        return
      }
      await (phase.phase === 'failed'
        ? regenerateSummary(artworkId, recordingId)
        : requestSummary(artworkId, recordingId).catch((err) =>
            err.code === 'FEEDBACK_INVALID_STATE'
              ? regenerateSummary(artworkId, recordingId)
              : Promise.reject(err),
          ))
      setSummary(await getSummaryStatus(artworkId, recordingId).catch(() => null))
      setMessage('AI 정리를 요청했어요. 정리가 끝나면 작품 화면의 녹음 카드에서 결과를 볼 수 있어요.')
    } catch (err) {
      if (err.code === 'AI_CONSENT_REQUIRED') {
        navigate('/ai-consent', { state: { from: location.pathname } })
        return
      }
      setMessage(
        err.code === 'RATE_LIMITED'
          ? '오늘 AI 정리 요청을 모두 사용했어요. 내일 다시 이용해 주세요.'
          : toErrorMessage(err),
      )
    } finally {
      setBusy(false)
    }
  }

  if (phase.phase === 'ready') {
    return (
      <Link to={`/feedbacks/${phase.feedbackId}`} className={styles.summaryLink}>
        <Sparkles size={18} aria-hidden />
        <span>AI 정리 결과 보기</span>
        <ChevronRight size={18} aria-hidden />
      </Link>
    )
  }
  return (
    <Card variant="soft" className={styles.notice}>
      {phase.phase === 'summarizing' ? (
        <p>AI가 이 대본으로 피드백을 정리하는 중이에요.</p>
      ) : features?.ai_summary === false ? (
        <p>AI 정리 기능이 아직 열리지 않았어요. 대본을 보며 직접 정리할 수 있어요.</p>
      ) : (
        <>
          <p>
            {phase.phase === 'failed'
              ? phase.message
              : '이 대본을 AI가 잘한 점·개선할 점·다음 연습 과제로 정리해 줘요.'}
          </p>
          {(phase.phase !== 'failed' || phase.retry) && (
            <Button size="md" onClick={handleSummarize} disabled={busy}>
              {busy ? '요청하는 중…' : '이 대본으로 AI 정리하기'}
            </Button>
          )}
        </>
      )}
      {message && <p role="status">{message}</p>}
    </Card>
  )
}

function TranscriptEditor({ artworkId, recordingId, transcript, onSaved }) {
  const player = useEvidencePlayer(artworkId, recordingId)
  const [editing, setEditing] = useState(false)
  const [texts, setTexts] = useState(() => transcript.segments.map((s) => s.text))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const changed = transcript.segments
    .map((s, i) => ({ index: s.index, text: texts[i].trim() }))
    .filter((s, i) => s.text && s.text !== transcript.segments[i].text)

  async function handleSave() {
    if (!changed.length) {
      setEditing(false)
      return
    }
    setBusy(true)
    setError('')
    try {
      await updateTranscript(artworkId, recordingId, {
        baseTranscriptId: transcript.id,
        segments: changed,
      })
      setNotice('대본을 고쳤어요. 이전 AI 정리 초안은 사라졌어요. 필요하면 아래에서 다시 정리해 주세요.')
      setEditing(false)
      setRefreshKey((n) => n + 1)
      onSaved()
    } catch (err) {
      setError(toErrorMessage(err))
      if (err.code === 'FEEDBACK_VERSION_CONFLICT') onSaved()
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <TopBar
        title="녹음 대본"
        belowHeader
        plain
        right={
          !editing && (
            <button type="button" className={styles.edit} onClick={() => setEditing(true)}>
              수정
            </button>
          )
        }
      />
      <main className={styles.body}>
        <p className={styles.lead}>
          녹음을 글로 바꾼 내용이에요. 잘못 알아들은 부분은 고칠 수 있어요 (처음 대본은 따로
          보관돼요).
          {transcript.edited && ' (수정한 대본)'}
        </p>
        {notice && (
          <p className={styles.lead} role="status">
            {notice}
          </p>
        )}

        <ol className={styles.segments}>
          {transcript.segments.map((s, i) => (
            <li key={s.index} className={styles.segment}>
              <button
                type="button"
                className={styles.time}
                onClick={() => player.play(s.index, s.start_ms, s.end_ms)}
                aria-label={`${formatDuration(s.start_ms)}부터 듣기`}
              >
                {player.playingKey === s.index ? <Pause size={12} /> : <Play size={12} />}
                {formatDuration(s.start_ms)}
              </button>
              {editing ? (
                <Textarea
                  aria-label={`${i + 1}번째 문장`}
                  rows={2}
                  maxLength={2000}
                  value={texts[i]}
                  onChange={(e) =>
                    setTexts((prev) => prev.map((t, j) => (j === i ? e.target.value : t)))
                  }
                  className={styles.input}
                />
              ) : (
                <p className={styles.text}>{s.text}</p>
              )}
            </li>
          ))}
        </ol>
        {player.error && <p className={styles.error}>{player.error}</p>}
        {error && <p className={styles.error}>{error}</p>}

        {!editing && (
          <SummaryPanel artworkId={artworkId} recordingId={recordingId} refreshKey={refreshKey} />
        )}

        {editing && (
          <div className={styles.actions}>
            <Button onClick={handleSave} disabled={busy}>
              {busy
                ? '저장하는 중…'
                : `저장하기${changed.length ? ` (${changed.length}문장)` : ''}`}
            </Button>
            <Button
              variant="soft"
              onClick={() => {
                setTexts(transcript.segments.map((s) => s.text))
                setEditing(false)
              }}
              disabled={busy}
            >
              취소
            </Button>
          </div>
        )}
      </main>
    </>
  )
}

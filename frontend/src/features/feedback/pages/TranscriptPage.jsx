import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, NotebookPen, Pause, Play } from 'lucide-react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Textarea } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  getAiFeatures,
  getSummaryStatus,
  getTranscript,
  regenerateSummary,
  updateTranscript,
} from '../aiApi'
import { aiPhase } from '../aiStatus'
import { formatDuration } from '../format'
import { processingPath } from '../processingFlow'
import { correctionView } from '../transcriptView'
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
  const fromProcessing = Boolean(useLocation().state?.fromProcessing)

  // 아직 대본이 없으면 진행 화면으로 (필요하면 글로 변환을 요청하고, 끝나면 이 화면으로 돌아옴).
  // 진행 화면에서 막 왔는데도 대본이 없으면 다시 보내지 않는다 (두 화면이 서로 돌려보내는 고리 방지)
  if (error?.code === 'TRANSCRIPT_NOT_READY') {
    if (!fromProcessing) {
      return <Navigate to={processingPath(artworkId, recordingId, 'transcript')} replace />
    }
    return (
      <FullScreenStatus
        title="대본을 아직 불러오지 못했어요"
        description="변환은 끝났는데 대본이 아직 보이지 않아요. 잠시 후 다시 불러와 주세요."
      >
        <Button onClick={reload}>다시 불러오기</Button>
      </FullScreenStatus>
    )
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

/**
 * 대본 아래 AI 정리: 누르면 진행 화면으로 (동의 확인·요청·완료 후 정리 결과로 이동은 진행 화면이 함).
 * 결과가 있으면 결과 보기
 */
function SummaryPanel({ artworkId, recordingId, refreshKey }) {
  const navigate = useNavigate()
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

  const summaryPath = processingPath(artworkId, recordingId, 'summary')

  async function handleSummarize() {
    if (busy) return
    if (phase.phase !== 'failed') {
      navigate(summaryPath)
      return
    }
    // 실패한 정리는 다시 요청한 뒤 진행 화면으로
    setBusy(true)
    setMessage('')
    try {
      await regenerateSummary(artworkId, recordingId)
      navigate(summaryPath)
    } catch (err) {
      console.warn('[transcript] summary retry failed', { code: err?.code ?? null })
      setMessage(
        err.code === 'RATE_LIMITED'
          ? '오늘 AI 정리 요청을 모두 사용했어요. 내일 다시 이용해 주세요.'
          : toErrorMessage(err),
      )
      setBusy(false)
    }
  }

  if (phase.phase === 'ready') {
    return (
      <Link to={`/feedbacks/${phase.feedbackId}`} className={styles.summaryLink}>
        <NotebookPen size={18} aria-hidden />
        <span>아트메이트 정리 보기</span>
        <ChevronRight size={18} aria-hidden />
      </Link>
    )
  }
  return (
    <Card variant="soft" className={styles.notice}>
      {phase.phase === 'summarizing' ? (
        <p>
          첨삭을 정리하고 있어요…{' '}
          <Link to={summaryPath} className={styles.inlineLink}>
            진행 상황 보기
          </Link>
        </p>
      ) : features?.ai_summary === false ? (
        <p>AI 서비스 설정이 필요해요. 대본을 보며 직접 정리할 수 있어요.</p>
      ) : (
        <>
          <p>
            {phase.phase === 'failed'
              ? phase.message
              : '이 대본을 아트메이트가 잘한 점·개선할 점·다음 연습 과제로 정리해 줘요.'}
          </p>
          {(phase.phase !== 'failed' || phase.retry) && (
            <Button size="md" onClick={handleSummarize} disabled={busy}>
              {busy ? '다시 요청하는 중…' : '아트메이트로 정리하기'}
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
  // v1.2 STT 원문·AI 문맥 보정 비교 (서버가 원문을 보존하고 보정본을 따로 저장)
  const correction = correctionView(transcript)
  const [showOriginal, setShowOriginal] = useState(false)

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
          {transcript.origin === 'EDITED' && ' (수정한 대본)'}
        </p>
        {(correction.notice || correction.hasOriginal) && !editing && (
          <Card variant="soft" className={styles.notice}>
            {correction.notice && (
              <p>
                <strong>AI 문맥 보정</strong> · {correction.notice}
              </p>
            )}
            {correction.hasOriginal && (
              <button
                type="button"
                className={styles.toggle}
                aria-pressed={showOriginal}
                onClick={() => setShowOriginal((v) => !v)}
              >
                {showOriginal ? '원본 STT 숨기기' : `원본 STT 보기 (${correction.differs.size}문장 다름)`}
              </button>
            )}
          </Card>
        )}
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
                <div className={styles.textBlock}>
                  <p className={styles.text}>
                    {s.text}
                    {correction.aiChanged.has(s.index) && (
                      <span className={styles.aiMark}>AI 보정</span>
                    )}
                  </p>
                  {showOriginal && correction.originalText(s.index) && (
                    <p className={styles.original}>
                      <span>원본</span> {correction.originalText(s.index)}
                    </p>
                  )}
                </div>
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

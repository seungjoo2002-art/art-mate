import { useCallback, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Textarea } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getTranscript, regenerateSummary, requestSummary, updateTranscript } from '../aiApi'
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

  if (error) {
    return (
      <FullScreenStatus title="원문을 불러오지 못했어요" description={toErrorMessage(error)}>
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

function TranscriptEditor({ artworkId, recordingId, transcript, onSaved }) {
  const player = useEvidencePlayer(artworkId, recordingId)
  const [editing, setEditing] = useState(false)
  const [texts, setTexts] = useState(() => transcript.segments.map((s) => s.text))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

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
      setNotice('원문을 고쳤어요. AI 정리 초안은 사라졌으니 다시 정리해 주세요.')
      setEditing(false)
      onSaved()
    } catch (err) {
      setError(toErrorMessage(err))
      if (err.code === 'FEEDBACK_VERSION_CONFLICT') onSaved()
    } finally {
      setBusy(false)
    }
  }

  async function handleResummarize() {
    setBusy(true)
    setError('')
    try {
      // 초안이 남아 있으면 409 → 다시 만들기
      await requestSummary(artworkId, recordingId).catch((err) =>
        err.code === 'FEEDBACK_INVALID_STATE'
          ? regenerateSummary(artworkId, recordingId)
          : Promise.reject(err),
      )
      setNotice('AI 정리를 다시 요청했어요. 작품 화면의 녹음 카드에서 진행 상태를 볼 수 있어요.')
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <TopBar
        title="녹음 원문"
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
          녹음을 글로 바꾼 내용이에요. 잘못 알아들은 부분은 고칠 수 있어요.
          {transcript.edited && ' (수정한 원문)'}
        </p>
        {notice && (
          <Card variant="soft" className={styles.notice}>
            {notice}
            {notice.startsWith('원문을 고쳤어요') && (
              <Button size="md" onClick={handleResummarize} disabled={busy}>
                AI로 다시 정리하기
              </Button>
            )}
          </Card>
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

import { useCallback, useState } from 'react'
import { Mic, Sparkles, Square } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getConsent, uploadRecording } from '../api'
import { startAiSummary } from '../aiApi'
import ConsentForm from '../components/ConsentForm'
import { formatDuration } from '../format'
import { useAudioRecorder } from '../useAudioRecorder'
import styles from './FeedbackRecordPage.module.css'

const WAVE = [14, 26, 18, 40, 22, 48, 30, 20, 38, 26, 16, 34, 28, 42, 20]

export default function FeedbackRecordPage() {
  const { artworkId } = useParams()
  const load = useCallback(() => getConsent(), [])
  const { data: consent, error, reload } = useAsync(load)

  if (error) {
    return (
      <FullScreenStatus title="정보를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!consent) return <FullScreenStatus />

  return (
    <>
      <TopBar title="피드백 녹음" belowHeader />
      <main className={styles.body}>
        {consent.is_valid ? (
          <Recorder artworkId={artworkId} />
        ) : (
          <ConsentForm requiredVersion={consent.required_version} onSaved={reload} />
        )}
      </main>
    </>
  )
}

function Recorder({ artworkId }) {
  const navigate = useNavigate()
  const { status, elapsedMs, result, error, start, stop, reset } = useAudioRecorder()
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const recording = status === 'recording'

  async function handleSave({ withAi = false } = {}) {
    setUploading(true)
    setUploadError('')
    let saved
    try {
      saved = await uploadRecording(artworkId, result)
    } catch (err) {
      // 녹음 파일은 그대로 두고 다시 저장할 수 있게 함
      setUploadError(toErrorMessage(err))
      setUploading(false)
      return
    }

    const artworkPath = `/artworks/${artworkId}`
    if (withAi) {
      try {
        const { needsConsent } = await startAiSummary(artworkId, saved.id)
        if (needsConsent) {
          // 동의 후 작품 화면에서 "AI로 피드백 정리하기"를 누르면 됨
          navigate('/ai-consent', { replace: true, state: { from: artworkPath } })
          return
        }
      } catch {
        // 녹음은 저장됨. AI 요청 실패는 작품 화면의 녹음 카드에서 다시 시도
      }
    }
    navigate(artworkPath, { replace: true })
  }

  return (
    <>
      <div className={`${styles.wave} ${recording ? styles.waveActive : ''}`} aria-hidden>
        {WAVE.map((height, i) => (
          <span key={i} style={{ height, animationDelay: `${i * 70}ms` }} />
        ))}
      </div>

      <div className={styles.clock}>
        {recording && <span className={styles.recDot} aria-hidden />}
        <span className={styles.time} role="timer">
          {formatDuration(elapsedMs)}
        </span>
      </div>
      <p className={styles.hint}>
        {recording
          ? '녹음 중이에요. 화면을 끄거나 다른 앱으로 이동하면 녹음이 멈출 수 있어요.'
          : status === 'recorded'
            ? '녹음을 들어 보고 저장해 주세요.'
            : '버튼을 눌러 녹음을 시작하세요'}
      </p>

      {status === 'recorded' ? (
        <div className={styles.review}>
          <audio controls src={result.url} className={styles.preview} />
          {uploadError && <p className={styles.error}>{uploadError}</p>}
          <Button onClick={() => handleSave({ withAi: true })} disabled={uploading}>
            <Sparkles size={20} aria-hidden />
            {uploading ? '저장하는 중…' : '저장하고 AI로 정리하기'}
          </Button>
          <Button variant="soft" onClick={() => handleSave()} disabled={uploading}>
            녹음만 저장하기
          </Button>
          <Button variant="soft" onClick={reset} disabled={uploading}>
            다시 녹음
          </Button>
        </div>
      ) : (
        <>
          <button
            type="button"
            className={`${styles.mic} ${recording ? styles.micRecording : ''}`}
            onClick={recording ? stop : start}
            aria-label={recording ? '녹음 멈추기' : '녹음 시작'}
          >
            {recording ? <Square size={30} fill="currentColor" /> : <Mic size={34} />}
          </button>
          {error && <p className={styles.error}>{error}</p>}
        </>
      )}
    </>
  )
}

import { useCallback, useState } from 'react'
import { Check, Mic, Square } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Checkbox } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getConsent, uploadRecording } from '../api'
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
  const [speakerNotified, setSpeakerNotified] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const recording = status === 'recording'

  async function handleSave() {
    setUploading(true)
    setUploadError('')
    try {
      await uploadRecording(artworkId, result)
      navigate(`/artworks/${artworkId}`, { replace: true })
    } catch (err) {
      // 녹음 파일은 그대로 두고 다시 저장할 수 있게 함
      setUploadError(toErrorMessage(err))
      setUploading(false)
    }
  }

  return (
    <>
      {/* 강사 목소리도 함께 녹음되므로 시작 전 확인 필수 (speaker_notice_confirmed) */}
      {speakerNotified ? (
        <p className={styles.notice}>
          <Check size={20} aria-hidden />
          선생님께 녹음 사실을 알렸어요.
        </p>
      ) : (
        <div className={styles.notice}>
          <Checkbox checked={speakerNotified} onChange={setSpeakerNotified}>
            선생님께 녹음한다고 말씀드렸어요.
          </Checkbox>
        </div>
      )}

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
          <Button onClick={handleSave} disabled={uploading}>
            {uploading ? '저장하는 중…' : '녹음 저장하기'}
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
            disabled={!speakerNotified}
            aria-label={recording ? '녹음 멈추기' : '녹음 시작'}
          >
            {recording ? <Square size={30} fill="currentColor" /> : <Mic size={34} />}
          </button>
          {error && <p className={styles.error}>{error}</p>}
          {!speakerNotified && (
            <p className={styles.hint}>선생님께 녹음 사실을 알린 뒤 시작할 수 있어요.</p>
          )}
        </>
      )}
      {/* TODO(v0.6): AI로 피드백 정리하기 */}
    </>
  )
}

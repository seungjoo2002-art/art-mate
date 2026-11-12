import { useCallback, useEffect, useState } from 'react'
import { FileAudio, Mic, Sparkles, Square } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getConsent, uploadRecording } from '../api'
import { getAiConsent, requestTranscription } from '../aiApi'
import { ACCEPT } from '../audioFile'
import BrowserSttStatus from '../components/BrowserSttStatus'
import ConsentForm from '../components/ConsentForm'
import { getPreference, resolvePlan, setPreference } from '../stt/browserStt'
import { startDeviceJob } from '../stt/deviceJobs'
import { useModelPrewarm } from '../stt/useBrowserStt'
import { formatDuration } from '../format'
import { useAudioRecorder } from '../useAudioRecorder'
import styles from './FeedbackRecordPage.module.css'

const WAVE = [14, 26, 18, 40, 22, 48, 30, 20, 38, 26, 16, 34, 28, 42, 20]
// 이보다 긴 녹음은 기기 변환에 시간이 오래 걸릴 수 있어 미리 알려 줌 (저장·변환은 가능)
const LONG_RECORDING_MS = 5 * 60 * 1000

/**
 * 저장(업로드) 후 글로 바꾸기 시작 (v0.9.3). 결과를 기다리지 않는다 — 작품 화면의 녹음 카드가
 * 진행 상태를 보여 준다. 녹음은 이미 서버에 저장됐으므로 변환 중 화면을 옮기거나 탭이 닫혀도 남는다.
 *  - 기기에서 변환 가능: 앱 안에서 계속 변환 (+ 서버 백업 작업을 미뤄서 만들어 둠)
 *  - 불가·사용 안 함·"서버에서 처리하기": 서버 전사 요청
 * AI 정리는 AI 전송 동의가 있을 때만 자동 요청. → { needsConsent }
 */
async function transcribeAfterUpload(artworkId, recordingId, blob, { serverOnly }) {
  const consent = await getAiConsent()
  const plan = serverOnly ? null : await resolvePlan()
  if (plan) {
    startDeviceJob({ artworkId, recordingId, blob, autoSummarize: consent.is_valid })
  } else {
    await requestTranscription(artworkId, recordingId, { autoSummarize: consent.is_valid }).catch(
      () => {}, // 실패하면 녹음 카드에서 다시 요청
    )
  }
  return { needsConsent: !consent.is_valid }
}

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
  const { status, elapsedMs, result, error, start, stop, reset, loadFile } = useAudioRecorder()
  const prewarm = useModelPrewarm()
  const [preference, setPreferenceState] = useState(getPreference)
  const [uploading, setUploading] = useState(false)
  const [loadingFile, setLoadingFile] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const recording = status === 'recording'
  const { start: startPrewarm, reset: resetPrewarm, skip: skipPrewarm } = prewarm
  const serverOnly = preference === 'off' || prewarm.state.phase === 'skipped'

  // 녹음이 끝나면(또는 파일을 고르면) 음성 인식 모델을 미리 준비 (변환은 저장 후)
  useEffect(() => {
    if (status !== 'recorded' || !result || preference === 'off') return
    startPrewarm()
  }, [status, result, preference, startPrewarm])

  function changePreference(value) {
    setPreference(value)
    setPreferenceState(value)
    resetPrewarm()
  }

  function handleReset() {
    resetPrewarm()
    reset()
  }

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
        const { needsConsent } = await transcribeAfterUpload(artworkId, saved.id, result.blob, {
          serverOnly,
        })
        if (needsConsent) {
          // 글로 바꾸기는 계속 진행. 동의 후 작품 화면에서 "AI로 피드백 정리하기"를 누르면 됨
          navigate('/ai-consent', { replace: true, state: { from: artworkPath } })
          return
        }
      } catch {
        // 녹음은 저장됨. 변환·AI 요청은 작품 화면의 녹음 카드에서 다시 시도
      }
    }
    navigate(artworkPath, { replace: true })
  }

  async function handleFile(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 파일을 다시 골라도 change가 발생하도록
    if (!file) return
    setLoadingFile(true)
    await loadFile(file)
    setLoadingFile(false)
  }

  const fromFile = Boolean(result?.fileName)

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
            ? fromFile
              ? `${result.fileName} · 들어 보고 저장해 주세요.`
              : '녹음을 들어 보고 저장해 주세요.'
            : '버튼을 눌러 녹음을 시작하세요'}
      </p>

      {status === 'recorded' ? (
        <div className={styles.review}>
          <audio controls src={result.url} className={styles.preview} />
          {result.durationMs > LONG_RECORDING_MS && (
            <p className={styles.hint}>
              5분이 넘는 녹음은 글로 바꾸는 데 시간이 오래 걸릴 수 있어요.
            </p>
          )}
          <BrowserSttStatus
            state={preference === 'off' ? { phase: 'skipped' } : prewarm.state}
            onSkip={skipPrewarm}
            preference={preference}
            onPreferenceChange={uploading ? undefined : changePreference}
            artworkId={artworkId}
          />
          {uploadError && <p className={styles.error}>{uploadError}</p>}
          <Button onClick={() => handleSave({ withAi: true })} disabled={uploading}>
            <Sparkles size={20} aria-hidden />
            {uploading ? '녹음 올리는 중…' : '저장하고 AI로 정리하기'}
          </Button>
          <Button variant="soft" onClick={() => handleSave()} disabled={uploading}>
            녹음만 저장하기
          </Button>
          <Button variant="soft" onClick={handleReset} disabled={uploading}>
            {fromFile ? '다른 방법으로 올리기' : '다시 녹음'}
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
          {!recording && (
            <label className={styles.fileButton} aria-busy={loadingFile}>
              <input
                type="file"
                accept={ACCEPT}
                className={styles.fileInput}
                onChange={handleFile}
                disabled={loadingFile}
              />
              <FileAudio size={20} aria-hidden />
              {loadingFile ? '파일 확인하는 중…' : '녹음 파일 올리기'}
            </label>
          )}
          {!recording && (
            <p className={styles.hint}>휴대폰 음성 메모 등 m4a·mp3·wav 파일 (25MB, 20분 이하)</p>
          )}
          {error && <p className={styles.error}>{error}</p>}
        </>
      )}
    </>
  )
}

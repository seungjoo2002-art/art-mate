import { useCallback, useEffect, useState } from 'react'
import { FileAudio, Mic, Sparkles, Square } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getConsent, uploadRecording } from '../api'
import { getAiConsent, requestSummary, requestTranscription, saveBrowserTranscript } from '../aiApi'
import { ACCEPT } from '../audioFile'
import BrowserSttStatus from '../components/BrowserSttStatus'
import ConsentForm from '../components/ConsentForm'
import { getPreference, setPreference } from '../stt/browserStt'
import { useBrowserStt, withTimeout } from '../stt/useBrowserStt'
import { formatDuration } from '../format'
import { useAudioRecorder } from '../useAudioRecorder'
import styles from './FeedbackRecordPage.module.css'

const WAVE = [14, 26, 18, 40, 22, 48, 30, 20, 38, 26, 16, 34, 28, 42, 20]
// 저장 버튼을 누른 뒤 기기 변환을 기다리는 최대 시간. 넘으면 서버(GitHub Actions)로 처리
const STT_WAIT_MS = 120_000

/**
 * 저장 후 전사·요약 요청. 기기 전사가 있으면 그것을 저장하고(대기 중 서버 작업은 취소됨),
 * 없거나 실패하면 기존처럼 서버 전사를 요청한다. → { needsConsent }
 */
async function transcribeAfterUpload(artworkId, recordingId, sttResult) {
  const consent = await getAiConsent()
  if (sttResult) {
    try {
      // AI 동의가 없으면 전사만 저장 (기기 안에서 만든 글이라 외부 전송 없음)
      await saveBrowserTranscript(artworkId, recordingId, sttResult, {
        autoSummarize: consent.is_valid,
      })
      return { needsConsent: !consent.is_valid }
    } catch (err) {
      if (err.code === 'TRANSCRIPTION_ALREADY_DONE') {
        if (consent.is_valid) await requestSummary(artworkId, recordingId).catch(() => {})
        return { needsConsent: !consent.is_valid }
      }
      // 그 밖의 오류는 서버 전사로 대신
    }
  }
  if (!consent.is_valid) return { needsConsent: true }
  try {
    await requestTranscription(artworkId, recordingId, { autoSummarize: true })
  } catch (err) {
    if (err.code !== 'TRANSCRIPTION_ALREADY_DONE') throw err
    await requestSummary(artworkId, recordingId)
  }
  return { needsConsent: false }
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
  const stt = useBrowserStt()
  const [preference, setPreferenceState] = useState(getPreference)
  const [uploading, setUploading] = useState(false)
  const [waitingStt, setWaitingStt] = useState(false)
  const [loadingFile, setLoadingFile] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const recording = status === 'recording'
  const { start: startStt, reset: resetStt, skip: skipStt } = stt

  // 녹음이 끝나면(또는 파일을 고르면) 바로 기기에서 글로 바꾸기 시작
  useEffect(() => {
    if (status !== 'recorded' || !result || preference === 'off') return
    startStt(result.blob)
  }, [status, result, preference, startStt])

  function changePreference(value) {
    setPreference(value)
    setPreferenceState(value)
    resetStt()
  }

  function handleReset() {
    skipStt()
    resetStt()
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
        setWaitingStt(true)
        const sttResult = preference === 'off' ? null : await withTimeout(stt.wait(), STT_WAIT_MS)
        setWaitingStt(false)
        const { needsConsent } = await transcribeAfterUpload(artworkId, saved.id, sttResult)
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
          <BrowserSttStatus
            state={preference === 'off' ? { phase: 'skipped' } : stt.state}
            onSkip={skipStt}
            preference={preference}
            onPreferenceChange={uploading ? undefined : changePreference}
            artworkId={artworkId}
          />
          {uploadError && <p className={styles.error}>{uploadError}</p>}
          <Button onClick={() => handleSave({ withAi: true })} disabled={uploading}>
            <Sparkles size={20} aria-hidden />
            {waitingStt ? '글로 바꾸기 마무리 중…' : uploading ? '저장하는 중…' : '저장하고 AI로 정리하기'}
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

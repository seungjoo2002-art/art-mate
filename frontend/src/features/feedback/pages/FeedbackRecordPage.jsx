import { useCallback, useState } from 'react'
import { FileAudio, Mic, NotebookPen, PencilLine, Square, Type } from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getConsent, uploadRecording } from '../api'
import { ACCEPT } from '../audioFile'
import { judgeSignal } from '../audioSignal'
import ConsentForm from '../components/ConsentForm'
import ReferencePicker from '../components/ReferencePicker'
import StagePicker from '../components/StagePicker'
import { presetRefs, referenceBody } from '../imageRefs'
import { processingPath } from '../processingFlow'
import { formatDuration } from '../format'
import { useAudioRecorder } from '../useAudioRecorder'
import styles from './FeedbackRecordPage.module.css'

const WAVE = [14, 26, 18, 40, 22, 48, 30, 20, 38, 26, 16, 34, 28, 42, 20]
// 이보다 긴 녹음은 기기 변환에 시간이 오래 걸릴 수 있어 미리 알려 줌 (저장·변환은 가능)
const LONG_RECORDING_MS = 5 * 60 * 1000

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
  // 작품 화면의 단계에서 들어오면 ?stage=단계 id (v0.9.7). 비우면 작품 전체 피드백
  const [params] = useSearchParams()
  const [stageId, setStageId] = useState(params.get('stage') ?? '')
  // v0.9.8 이 피드백을 받을 때 본 작품 사진
  // 작품 화면에서 보던 사진(?photo=)을 기본 기준 사진으로
  const [refs, setRefs] = useState(() => presetRefs(params.get('photo')))
  const { status, elapsedMs, result, error, silentInput, start, stop, reset, loadFile } =
    useAudioRecorder()
  const [uploading, setUploading] = useState(false)
  const [loadingFile, setLoadingFile] = useState(false)
  const [uploadError, setUploadError] = useState('')
  // 이미 올린 녹음 (다시 누르면 업로드를 반복하지 않고 이어서 진행)
  const [savedId, setSavedId] = useState(null)
  const recording = status === 'recording'
  // 'silent' | 'quiet' | 'ok' — 소리가 거의 없는 녹음은 글로 바꾸지 않는다 (Whisper가 없는 문장을 만들어 냄)
  const signal = judgeSignal(result?.signal)

  function handleReset() {
    setSavedId(null)
    reset()
  }

  /**
   * 녹음 저장 → (goal이 있으면) 진행 화면으로 바로 이동. 전사·AI 정리 요청은 진행 화면이 서버에 보낸다.
   * goal: 'transcript'(글로 변환하기) | 'summary'(AI로 정리하기) | null(녹음만 저장)
   */
  async function handleSave(goal = null) {
    if (uploading) return // 중복 클릭 방지
    setUploading(true)
    setUploadError('')
    let id = savedId
    if (!id) {
      try {
        const saved = await uploadRecording(artworkId, {
          ...result,
          stageId: stageId || undefined,
          references: referenceBody(refs),
        })
        id = saved.id
        setSavedId(id)
      } catch (err) {
        // 녹음 파일은 이 화면에 그대로 두고 다시 저장할 수 있게 함
        console.warn('[recording] upload failed', {
          code: err?.code ?? null,
          status: err?.status ?? null,
        })
        setUploadError(toErrorMessage(err))
        setUploading(false)
        return
      }
    }
    navigate(goal ? processingPath(artworkId, id, goal) : `/artworks/${artworkId}`, {
      replace: true,
    })
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

      {recording && silentInput && (
        <p className={styles.error} role="alert">
          마이크 소리가 들어오지 않아요. 마이크를 가리고 있지 않은지, 다른 앱이 마이크를 쓰고 있지
          않은지 확인해 주세요.
        </p>
      )}

      {status === 'recorded' ? (
        <div className={styles.review}>
          <audio controls src={result.url} className={styles.preview} />
          {signal === 'silent' && (
            <p className={styles.error} role="alert">
              이 녹음에는 소리가 거의 없어요. 재생해서 확인한 뒤 다시 녹음해 주세요. 그대로 저장하면
              녹음만 저장되고 글로 바꾸지는 않아요.
            </p>
          )}
          {signal === 'quiet' && (
            <p className={styles.hint}>
              소리가 작게 녹음됐어요. 휴대폰을 말하는 사람 가까이에 두면 글로 더 정확하게 바꿀 수 있어요.
            </p>
          )}
          {result.durationMs > LONG_RECORDING_MS && (
            <p className={styles.hint}>
              5분이 넘는 녹음은 글로 바꾸는 데 시간이 오래 걸릴 수 있어요.
            </p>
          )}
          <StagePicker artworkId={artworkId} value={stageId} onChange={setStageId} />
          <ReferencePicker
            artworkId={artworkId}
            stageId={stageId}
            value={refs}
            onChange={setRefs}
          />
          {uploadError && <p className={styles.error}>{uploadError}</p>}
          {signal !== 'silent' && (
            <>
              <Button onClick={() => handleSave('summary')} disabled={uploading}>
                <NotebookPen size={20} aria-hidden />
                {uploading ? '녹음 올리는 중…' : '아트메이트로 정리하기'}
              </Button>
              <Button variant="soft" onClick={() => handleSave('transcript')} disabled={uploading}>
                <Type size={20} aria-hidden />
                글로 변환하기
              </Button>
            </>
          )}
          <Button variant="soft" onClick={() => handleSave()} disabled={uploading}>
            녹음만 저장하기
          </Button>
          <Link to={`/artworks/${artworkId}/notes/new`} className={styles.noteLink}>
            <PencilLine size={14} aria-hidden /> 들은 내용을 직접 글로 적기
          </Link>
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

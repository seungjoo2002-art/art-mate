import { useCallback, useEffect, useRef, useState } from 'react'
import { MAX_AUDIO_BYTES, MAX_AUDIO_MS, audioTypeOf, readDurationMs } from './audioFile'
import { analyzeBlob, watchInputLevel } from './audioSignal'

const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']

/** Safari(iPhone·Mac)는 자체 형식인 mp4(AAC)를 먼저 — 모든 브라우저에서 재생되는 형식 */
export function recordingTypes(userAgent = globalThis.navigator?.userAgent ?? '') {
  const safari = /Safari/.test(userAgent) && !/Chrome|Chromium|CriOS|FxiOS|EdgiOS|Android/.test(userAgent)
  return safari ? ['audio/mp4', ...TYPES.filter((t) => t !== 'audio/mp4')] : TYPES
}
const MAX_DURATION_MS = MAX_AUDIO_MS // 서버 제한 20분

/**
 * 브라우저 마이크 녹음 (v0.5 문서 §2.4) 또는 녹음 파일 불러오기(loadFile)
 * status: idle → recording → recorded  (파일: idle → recorded)
 * result: { blob, mimeType, durationMs, recordedAt(시작 시각), url(미리듣기용), fileName?, signal? }
 *   signal: { peak, speechRatio } 녹음에 실제 소리가 있었는지 (audioSignal.judgeSignal로 판단, 모르면 null)
 * silentInput: 녹음 중 마이크 소리가 몇 초째 들어오지 않음 (마이크 선택·권한·하드웨어 문제)
 */
export function useAudioRecorder() {
  const [status, setStatus] = useState('idle')
  const [elapsedMs, setElapsedMs] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [silentInput, setSilentInput] = useState(false)
  const recorderRef = useRef(null)
  const monitorRef = useRef(null)
  const streamRef = useRef(null)
  const timerRef = useRef(null)

  const releaseMic = useCallback(() => {
    clearInterval(timerRef.current)
    const signal = monitorRef.current?.stop() ?? null
    monitorRef.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop()) // 마이크 표시등 끄기
    streamRef.current = null
    return signal
  }, [])

  const stop = useCallback(() => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }, [])

  // iOS Safari: 버튼 클릭 핸들러 안에서 바로 호출해야 함
  const start = useCallback(async () => {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('이 브라우저에서는 녹음을 지원하지 않아요.')
      return
    }
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err) {
      setError(
        err.name === 'NotAllowedError'
          ? '마이크 권한이 필요해요. 브라우저 설정에서 마이크를 허용해 주세요.'
          : '마이크를 사용할 수 없어요.',
      )
      return
    }

    const mimeType = recordingTypes().find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
    const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64_000 })
    const chunks = []
    let startedAt = 0
    let startedAtIso = null // 타임라인 정렬용 실제 시작 시각

    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    recorder.onstart = () => {
      startedAt = performance.now()
      startedAtIso = new Date().toISOString()
      timerRef.current = setInterval(() => {
        const elapsed = performance.now() - startedAt
        setElapsedMs(elapsed)
        if (elapsed >= MAX_DURATION_MS) recorder.stop()
      }, 250)
    }
    recorder.onstop = () => {
      const signal = releaseMic()
      setSilentInput(false)
      // WebM은 파일에 길이 정보가 없을 수 있어 직접 잰 값을 사용
      const durationMs = Math.round(performance.now() - startedAt)
      const blob = new Blob(chunks, { type: recorder.mimeType })
      setResult({
        blob,
        mimeType: recorder.mimeType,
        durationMs,
        recordedAt: startedAtIso,
        url: URL.createObjectURL(blob),
        signal,
      })
      setElapsedMs(durationMs)
      setStatus('recorded')
    }

    streamRef.current = stream
    recorderRef.current = recorder
    setSilentInput(false)
    // 마이크 입력 감시 (읽기만, 녹음 내용은 바꾸지 않음)
    monitorRef.current = watchInputLevel(stream, { onSilent: setSilentInput })
    setElapsedMs(0)
    setStatus('recording')
    recorder.start(1000) // 1초마다 청크 (긴 녹음에서 유실 방지)
  }, [releaseMic])

  /** 휴대폰 음성 메모 등 이미 있는 녹음 파일. 형식·크기·길이를 검사한 뒤 녹음한 것처럼 미리듣기 상태로 */
  const loadFile = useCallback(async (file) => {
    setError('')
    const mimeType = audioTypeOf(file)
    if (!mimeType) {
      setError('m4a, mp3, wav, webm, ogg 녹음 파일만 올릴 수 있어요.')
      return
    }
    if (file.size > MAX_AUDIO_BYTES) {
      setError('25MB 이하 파일만 올릴 수 있어요.')
      return
    }
    const url = URL.createObjectURL(file)
    let durationMs
    try {
      durationMs = await readDurationMs(url)
    } catch {
      URL.revokeObjectURL(url)
      setError('이 파일은 재생할 수 없어요. 다른 파일을 골라 주세요.')
      return
    }
    if (durationMs > MAX_AUDIO_MS) {
      URL.revokeObjectURL(url)
      setError('20분 이하 녹음만 올릴 수 있어요. 나눠서 올려 주세요.')
      return
    }
    // 파일에 실제 소리가 있는지 (5분 이하만, 이 기기 안에서만 검사)
    const signal = await analyzeBlob(file, { durationMs })
    setResult({
      blob: file,
      mimeType,
      durationMs,
      signal,
      // 녹음한 시각을 알 수 없어 파일 수정 시각을 사용 (타임라인 정렬용)
      recordedAt: new Date(file.lastModified || Date.now()).toISOString(),
      url,
      fileName: file.name,
    })
    setElapsedMs(durationMs)
    setStatus('recorded')
  }, [])

  const reset = useCallback(() => {
    setResult((prev) => {
      if (prev) URL.revokeObjectURL(prev.url)
      return null
    })
    setElapsedMs(0)
    setStatus('idle')
  }, [])

  // 화면을 떠나면 녹음 중단 + 마이크 해제
  useEffect(
    () => () => {
      if (recorderRef.current?.state === 'recording') {
        recorderRef.current.onstop = null
        recorderRef.current.stop()
      }
      releaseMic()
    },
    [releaseMic],
  )

  return { status, elapsedMs, result, error, silentInput, start, stop, reset, loadFile }
}

import { useCallback, useEffect, useRef, useState } from 'react'

const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
const MAX_DURATION_MS = 20 * 60 * 1000 // 서버 제한 20분

/**
 * 브라우저 마이크 녹음 (v0.5 문서 §2.4)
 * status: idle → recording → recorded
 * result: { blob, mimeType, durationMs, url(미리듣기용) }
 */
export function useAudioRecorder() {
  const [status, setStatus] = useState('idle')
  const [elapsedMs, setElapsedMs] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const recorderRef = useRef(null)
  const streamRef = useRef(null)
  const timerRef = useRef(null)

  const releaseMic = useCallback(() => {
    clearInterval(timerRef.current)
    streamRef.current?.getTracks().forEach((track) => track.stop()) // 마이크 표시등 끄기
    streamRef.current = null
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

    const mimeType = TYPES.find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
    const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64_000 })
    const chunks = []
    let startedAt = 0

    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    recorder.onstart = () => {
      startedAt = performance.now()
      timerRef.current = setInterval(() => {
        const elapsed = performance.now() - startedAt
        setElapsedMs(elapsed)
        if (elapsed >= MAX_DURATION_MS) recorder.stop()
      }, 250)
    }
    recorder.onstop = () => {
      releaseMic()
      // WebM은 파일에 길이 정보가 없을 수 있어 직접 잰 값을 사용
      const durationMs = Math.round(performance.now() - startedAt)
      const blob = new Blob(chunks, { type: recorder.mimeType })
      setResult({ blob, mimeType: recorder.mimeType, durationMs, url: URL.createObjectURL(blob) })
      setElapsedMs(durationMs)
      setStatus('recorded')
    }

    streamRef.current = stream
    recorderRef.current = recorder
    setElapsedMs(0)
    setStatus('recording')
    recorder.start(1000) // 1초마다 청크 (긴 녹음에서 유실 방지)
  }, [releaseMic])

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

  return { status, elapsedMs, result, error, start, stop, reset }
}

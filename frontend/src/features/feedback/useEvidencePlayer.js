import { useCallback, useEffect, useRef, useState } from 'react'
import { getRecordingUrl } from './api'

/**
 * "근거 듣기": 녹음의 start_ms~end_ms 구간만 재생
 * 재생 URL은 처음 누를 때 받음 (Signed URL은 몇 분 뒤 만료되므로 매번 새로 받음)
 */
export function useEvidencePlayer(artworkId, recordingId) {
  const audioRef = useRef(null)
  const stopAtRef = useRef(null)
  const [playingKey, setPlayingKey] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const audio = new Audio()
    audio.preload = 'none'
    const onTime = () => {
      if (stopAtRef.current !== null && audio.currentTime * 1000 >= stopAtRef.current) {
        audio.pause()
      }
    }
    const onStop = () => setPlayingKey(null)
    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('pause', onStop)
    audio.addEventListener('ended', onStop)
    audioRef.current = audio
    return () => {
      audio.pause()
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('pause', onStop)
      audio.removeEventListener('ended', onStop)
    }
  }, [])

  const play = useCallback(
    async (key, startMs, endMs) => {
      const audio = audioRef.current
      if (!audio || !recordingId) return
      if (playingKey === key) {
        audio.pause()
        return
      }
      setError('')
      try {
        const { url } = await getRecordingUrl(artworkId, recordingId)
        if (audio.src !== url) audio.src = url
        stopAtRef.current = endMs ?? null
        audio.currentTime = (startMs ?? 0) / 1000
        await audio.play()
        setPlayingKey(key)
      } catch {
        setError('녹음을 재생할 수 없어요.')
      }
    },
    [artworkId, recordingId, playingKey],
  )

  return { play, playingKey, error }
}

import { useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { getRecordingUrl } from '../api'
import { formatDuration } from '../format'
import styles from './RecordingPlayer.module.css'

/**
 * 한 줄짜리 녹음 플레이어: 재생 버튼 + 진행 바 + 시간
 * 비공개 버킷이라 Signed URL 만료로 오류가 나면 한 번 새 URL을 받아 재시도
 * 길이는 duration_ms 사용 (WebM은 <audio>.duration이 Infinity일 수 있음)
 */
export default function RecordingPlayer({ artworkId, recording }) {
  const audioRef = useRef(null)
  const [freshUrl, setFreshUrl] = useState(null)
  const [retried, setRetried] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [currentMs, setCurrentMs] = useState(0)
  const needsUrl = !recording.url
  const totalMs = recording.duration_ms

  useEffect(() => {
    if (!needsUrl) return
    let cancelled = false
    getRecordingUrl(artworkId, recording.id).then(
      (signed) => !cancelled && setFreshUrl(signed.url),
      () => {},
    )
    return () => {
      cancelled = true
    }
  }, [needsUrl, artworkId, recording.id])

  async function handleError() {
    if (retried) return
    setRetried(true)
    try {
      const signed = await getRecordingUrl(artworkId, recording.id)
      setFreshUrl(signed.url)
    } catch {
      // 무시
    }
  }

  function toggle() {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) audio.play().catch(() => setPlaying(false))
    else audio.pause()
  }

  function seek(e) {
    const audio = audioRef.current
    if (!audio || !totalMs) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
    audio.currentTime = (ratio * totalMs) / 1000
  }

  const src = freshUrl ?? recording.url
  const progress = totalMs ? Math.min(100, (currentMs / totalMs) * 100) : 0

  return (
    <div className={styles.player}>
      <audio
        ref={audioRef}
        src={src ?? undefined}
        preload="metadata"
        onError={handleError}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false)
          setCurrentMs(0)
        }}
        onTimeUpdate={(e) => setCurrentMs(e.currentTarget.currentTime * 1000)}
      />
      <button
        type="button"
        className={styles.play}
        onClick={toggle}
        disabled={!src}
        aria-label={playing ? '일시정지' : '재생'}
      >
        {playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
      </button>
      <div
        className={styles.track}
        onClick={seek}
        role="slider"
        aria-label="재생 위치"
        aria-valuemin={0}
        aria-valuemax={Math.round(totalMs / 1000)}
        aria-valuenow={Math.round(currentMs / 1000)}
      >
        <span className={styles.fill} style={{ width: `${progress}%` }} />
      </div>
      <span className={styles.time}>
        {playing || currentMs > 0 ? formatDuration(currentMs) : formatDuration(totalMs)}
      </span>
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { getTimer, sendTimerEvent } from '../../features/artworks/api'

/**
 * 서버 타이머 상태 + 1초마다 화면에서 계산한 경과 시간
 * (v0.9 문서: RUNNING이면 elapsed_seconds + (지금 − server_time))
 */
export function useExamTimer(artworkId) {
  const [timer, setTimer] = useState(null)
  const [error, setError] = useState(null)
  const [offset, setOffset] = useState(0) // 서버 시각 − 내 기기 시각 (ms)
  const [now, setNow] = useState(() => Date.now())

  const apply = useCallback((next) => {
    setOffset(Date.parse(next.server_time) - Date.now())
    setTimer(next)
  }, [])

  // 처음 열면 상태를 받고, 아직 시작 전이면 시작
  useEffect(() => {
    let cancelled = false
    getTimer(artworkId)
      .then((current) => (current.state === 'IDLE' ? sendTimerEvent(artworkId, 'START') : current))
      .then(
        (next) => !cancelled && apply(next),
        (err) => !cancelled && setError(err),
      )
    return () => {
      cancelled = true
    }
  }, [artworkId, apply])

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const send = useCallback(
    async (event) => {
      const next = await sendTimerEvent(artworkId, event)
      apply(next)
      return next
    },
    [artworkId, apply],
  )

  let elapsed = timer?.elapsed_seconds ?? 0
  if (timer?.state === 'RUNNING') {
    elapsed += Math.max(0, Math.floor((now + offset - Date.parse(timer.server_time)) / 1000))
  }
  const limitSeconds = (timer?.time_limit_minutes ?? 0) * 60

  return { timer, error, elapsed, limitSeconds, send }
}

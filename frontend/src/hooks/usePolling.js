import { useEffect } from 'react'

/**
 * active인 동안 delay(ms)마다 onTick 실행. 화면이 숨겨져 있으면 다시 보일 때까지 기다림
 * deps가 바뀔 때마다(보통 새 응답) 타이머를 새로 잡음
 */
export function usePolling(active, delay, onTick, deps = []) {
  useEffect(() => {
    if (!active) return
    const tick = () => {
      if (document.visibilityState !== 'visible') {
        document.addEventListener('visibilitychange', tick, { once: true })
        return
      }
      onTick()
    }
    const id = setTimeout(tick, delay)
    return () => {
      clearTimeout(id)
      document.removeEventListener('visibilitychange', tick)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, delay, onTick, ...deps])
}

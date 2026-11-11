import { useCallback, useEffect, useRef, useState } from 'react'
import { cancelBrowserStt, resolvePlan, transcribeBlob } from './browserStt'

/**
 * 브라우저(기기) 음성 인식 상태
 * phase: idle → (unsupported | preparing → transcribing → done | failed | skipped)
 *  - unsupported/failed/skipped면 저장 후 기존 서버(GitHub Actions) 전사로 대신한다
 * wait(): 결과 Promise (성공 결과 또는 null). start 전에 불러도 된다
 */
export function useBrowserStt() {
  const [state, setState] = useState({ phase: 'idle' })
  const runRef = useRef(null)
  const generationRef = useRef(0)

  const start = useCallback((blob) => {
    const generation = ++generationRef.current
    const update = (next) => {
      if (generationRef.current === generation) setState(next)
    }
    runRef.current = (async () => {
      const plan = await resolvePlan()
      if (!plan) {
        update({ phase: 'unsupported' })
        return null
      }
      update({ phase: 'preparing', plan, progress: null })
      try {
        const result = await transcribeBlob(blob, plan, {
          onStage: (stage) =>
            update((prev) => ({ ...prev, phase: stage === 'loading' ? 'preparing' : 'transcribing' })),
          onProgress: (progress) => update((prev) => ({ ...prev, progress })),
        })
        update({ phase: 'done', plan, result })
        return generationRef.current === generation ? result : null
      } catch (error) {
        update({
          phase: error.message === 'cancelled' ? 'skipped' : 'failed',
          plan,
          error: error.message,
        })
        return null
      }
    })()
    return runRef.current
  }, [])

  const wait = useCallback(() => runRef.current ?? Promise.resolve(null), [])

  /** 서버에서 처리하기: 기기 변환 중단 */
  const skip = useCallback(() => {
    generationRef.current += 1
    cancelBrowserStt()
    runRef.current = Promise.resolve(null)
    setState({ phase: 'skipped' })
  }, [])

  const reset = useCallback(() => {
    generationRef.current += 1
    runRef.current = null
    setState({ phase: 'idle' })
  }, [])

  // 화면을 떠나도 Worker·모델은 유지 (다음 녹음에서 바로 사용). 결과만 버린다
  useEffect(() => () => {
    generationRef.current += 1
  }, [])

  return { state, start, wait, skip, reset }
}

/** 제한 시간 안에 끝나지 않으면 null (→ 서버 처리) */
export function withTimeout(promise, ms) {
  return Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(null), ms))])
}

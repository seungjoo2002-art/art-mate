import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { cancelBrowserStt, prewarm, resolvePlan } from './browserStt'
import { getDeviceJob, hasBusyDeviceJob, subscribe } from './deviceJobs'

/** 이 녹음의 기기 전사 작업 상태 (deviceJobs.js, 화면을 옮겨도 유지). 없으면 null */
export function useDeviceJob(recordingId) {
  return useSyncExternalStore(
    subscribe,
    () => getDeviceJob(recordingId),
    () => null,
  )
}

/**
 * 녹음 직후 음성 인식 모델만 미리 준비 (가장 오래 걸리는 단계). 실제 변환은 업로드 후 deviceJobs에서.
 * phase: idle → unsupported | preparing → ready | failed(저장 때 다시 시도) | skipped(서버 처리 선택)
 */
export function useModelPrewarm() {
  const [state, setState] = useState({ phase: 'idle' })
  const generationRef = useRef(0)

  const start = useCallback(async () => {
    const generation = ++generationRef.current
    const update = (next) => {
      if (generationRef.current === generation) setState(next)
    }
    const plan = await resolvePlan()
    if (!plan) {
      update({ phase: 'unsupported' })
      return
    }
    update({ phase: 'preparing', plan, progress: null })
    const loaded = await prewarm(plan, {
      onProgress: (progress) => update((prev) => ({ ...prev, progress })),
    })
    update(loaded ? { phase: 'ready', plan, loaded } : { phase: 'failed', plan })
  }, [])

  /** "서버에서 처리하기": 모델 준비를 멈추고 이번 녹음은 서버로 */
  const skip = useCallback(() => {
    generationRef.current += 1
    if (!hasBusyDeviceJob()) cancelBrowserStt() // 다른 녹음 변환 중이면 Worker는 그대로
    setState({ phase: 'skipped' })
  }, [])

  const reset = useCallback(() => {
    generationRef.current += 1
    setState({ phase: 'idle' })
  }, [])

  // 화면을 떠나도 Worker·모델은 유지 (바로 이어지는 변환에서 사용). 결과 표시만 멈춤
  useEffect(
    () => () => {
      generationRef.current += 1
    },
    [],
  )

  return { state, start, skip, reset }
}

/** 제한 시간 안에 끝나지 않으면 null */
export function withTimeout(promise, ms) {
  return Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(null), ms))])
}

import { useCallback, useEffect, useState } from 'react'
import { getExam, nextExamStage, putExamPlan, sendTimerEvent } from '../../features/artworks/api'
import { loadExamDefaults, toPlan } from '../../features/artworks/exam'

/** 처음 열 때: 단계 계획이 없으면 기본 목표로 저장 → 시작 전이면 START → 최신 단계 상태 */
async function openExam(artworkId) {
  let exam = await getExam(artworkId)
  if (exam.timer.state !== 'IDLE') return exam
  // 계획은 START 전에 있어야 첫 단계가 함께 시작됨 (예전 버전에서 만든 시험 작품 대비)
  if (!exam.stages.length) await putExamPlan(artworkId, toPlan(await loadExamDefaults()))
  try {
    await sendTimerEvent(artworkId, 'START')
  } catch (err) {
    // 동시에 두 번 시작하면(개발 모드 이중 실행, 탭 2개 등) 한쪽은 409 → 현재 상태를 다시 받음
    if (err.code !== 'TIMER_INVALID_TRANSITION') throw err
  }
  exam = await getExam(artworkId)
  return exam
}

/**
 * 서버 시험 상태(단계 + 타이머) + 1초마다 화면에서 계산한 경과 시간
 * (v0.9 문서: RUNNING이면 elapsed_seconds + (지금 − server_time))
 */
export function useExamTimer(artworkId) {
  const [exam, setExam] = useState(null)
  const [error, setError] = useState(null)
  const [offset, setOffset] = useState(0) // 서버 시각 − 내 기기 시각 (ms)
  const [now, setNow] = useState(() => Date.now())

  const apply = useCallback((next) => {
    setOffset(Date.parse(next.timer.server_time) - Date.now())
    setExam(next)
  }, [])

  useEffect(() => {
    let cancelled = false
    openExam(artworkId).then(
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

  /** 타이머 이벤트 (STOP 등). 단계 상태도 다시 받음 */
  const send = useCallback(
    async (event) => {
      const timer = await sendTimerEvent(artworkId, event)
      apply(await getExam(artworkId))
      return timer
    },
    [artworkId, apply],
  )

  /** 다음 단계로 (current_stage로 중복 전환 방지) */
  const next = useCallback(
    async (currentStage) => apply(await nextExamStage(artworkId, currentStage)),
    [artworkId, apply],
  )

  const reload = useCallback(async () => apply(await getExam(artworkId)), [artworkId, apply])

  const timer = exam?.timer
  let elapsed = timer?.elapsed_seconds ?? 0
  if (timer?.state === 'RUNNING') {
    elapsed += Math.max(0, Math.floor((now + offset - Date.parse(timer.server_time)) / 1000))
  }
  const limitSeconds = (timer?.time_limit_minutes ?? exam?.total_target_minutes ?? 0) * 60

  return { exam, timer, error, elapsed, limitSeconds, send, next, reload }
}

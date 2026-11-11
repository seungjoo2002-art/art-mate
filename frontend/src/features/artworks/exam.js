// 실기시험 모드 (모의시험 작품 + 제한 시간)

// 디자인의 시험 단계별 목표 시간. 백엔드는 작품에 전체 제한 시간(time_limit_minutes)만 저장하므로
// 단계별 값은 이 기기에 기본값으로만 기억하고, 합계를 제한 시간으로 보냄
export const DEFAULT_STAGE_TARGETS = [
  { key: 'IDEA', label: '아이디어', minutes: 40 },
  { key: 'SKETCH', label: '스케치', minutes: 80 },
  { key: 'COLOR', label: '채색', minutes: 180 },
]
export const MAX_EXAM_MINUTES = 1440 // 서버 제한 (1~1440분)

const KEY = 'artmate.examStageTargets'

export function loadStageTargets() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY))
    if (Array.isArray(saved) && saved.length === DEFAULT_STAGE_TARGETS.length) {
      return DEFAULT_STAGE_TARGETS.map((stage, i) => ({
        ...stage,
        minutes: Number(saved[i]?.minutes) || stage.minutes,
      }))
    }
  } catch {
    // 저장소를 못 쓰면 기본값
  }
  return DEFAULT_STAGE_TARGETS
}

export function saveStageTargets(targets) {
  try {
    localStorage.setItem(KEY, JSON.stringify(targets.map(({ key, minutes }) => ({ key, minutes }))))
  } catch {
    // 무시 (다음에 기본값으로 시작)
  }
}

export const totalMinutes = (targets) => targets.reduce((sum, t) => sum + t.minutes, 0)

/** 200 → "3시간 20분" */
export function formatMinutes(minutes) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (!h) return `${m}분`
  return m ? `${h}시간 ${m}분` : `${h}시간`
}

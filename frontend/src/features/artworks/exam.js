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

// 시험 진행 기록 (이 기기에만): 단계별 목표, 단계 시작 시점(경과 초), 단계별 메모 id
// 타이머 API에는 단계 구분이 없어서 "다음 단계"를 누른 시점으로 단계별 실제 시간을 계산함
export const EXAM_PHOTO_STAGES = ['SKETCH', 'PROGRESS', 'FINAL'] // 아이디어·스케치·채색 → 사진 단계

const sessionKey = (artworkId) => `artmate.exam.${artworkId}`

export function loadExamSession(artworkId) {
  try {
    const saved = JSON.parse(localStorage.getItem(sessionKey(artworkId)))
    if (saved && Array.isArray(saved.stageStarts)) return saved
  } catch {
    // 무시
  }
  return null
}

export function saveExamSession(artworkId, session) {
  try {
    localStorage.setItem(sessionKey(artworkId), JSON.stringify(session))
  } catch {
    // 무시 (단계별 시간만 못 보여 줌)
  }
}

export function newExamSession(targets) {
  return {
    targets: targets.map(({ key, label, minutes }) => ({ key, label, minutes })),
    stageStarts: [0], // 단계마다 시작한 시점의 경과 초
    notes: {}, // { 단계 index: [note id] }
  }
}

/** 단계별 실제 시간(초). 끝난 단계는 다음 단계 시작까지, 현재 단계는 지금(elapsed)까지 */
export function stageSeconds(session, elapsed) {
  return session.targets.map((_, i) => {
    const start = session.stageStarts[i]
    if (start === undefined) return 0
    const end = session.stageStarts[i + 1] ?? elapsed
    return Math.max(0, end - start)
  })
}

const pad = (n) => String(n).padStart(2, '0')

/** 초 → "04:59:50" */
export function formatClock(seconds) {
  const s = Math.abs(Math.floor(seconds))
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`
}

/** 초 → "57초" / "12분 3초" / "1시간 20분" */
export function formatDurationSeconds(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}초`
  if (s < 3600) return s % 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s / 60}분`
  return formatMinutes(Math.round(s / 60))
}

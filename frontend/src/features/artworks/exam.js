import { getExamDefaults, putExamDefaults } from './api'

// 실기시험 모드 (모의시험 작품 + 서버에 저장되는 단계별 목표·진행)

// 시험 단계 코드 → 이름 (서버 EXAM_STAGE_LABELS와 같음)
export const STAGE_LABELS = { IDEA: '아이디어', SKETCH: '스케치', COLOR: '채색', FINISH: '마무리' }

// 화면용 단계 목표: { key: 단계 코드, label, minutes }
export const DEFAULT_STAGE_TARGETS = [
  { key: 'IDEA', label: '아이디어', minutes: 40 },
  { key: 'SKETCH', label: '스케치', minutes: 80 },
  { key: 'COLOR', label: '채색', minutes: 180 },
]
export const MAX_EXAM_MINUTES = 1440 // 서버 제한 (합계 1~1440분)

// v0.9.7: 시험 단계 이름은 학생이 정하고 작품 단계(stage_plan)로 저장한다. 서버 시험 진행은 단계 코드
// 최대 4개를 쓰므로, 시험 단계 i ↔ 작품 단계 i (같은 순서)로 대응하고 코드는 순서대로 붙인다
export const EXAM_CODES = ['IDEA', 'SKETCH', 'COLOR', 'FINISH']
export const MAX_EXAM_STAGES = EXAM_CODES.length

/** 편집 목록 [{ name, minutes }] → 서버 시험 계획 [{ stage: 코드, target_minutes }] (순서대로) */
export const rowsToPlan = (rows) =>
  rows.map((row, i) => ({ stage: EXAM_CODES[i], target_minutes: row.minutes }))

/**
 * 시험 단계(서버)에 대응하는 작품 단계. 단계 수가 같을 때만 순서로 맞춤
 * (예전 시험·단계를 나중에 바꾼 작품은 대응하지 않음 → 예전 고정 사진 단계로)
 */
export function artworkStageFor(artwork, examStages, index) {
  const plan = artwork.stage_plan ?? []
  return plan.length === examStages.length ? (plan[index] ?? null) : null
}

/** 화면에 보여 줄 시험 단계 이름: 대응하는 작품 단계 이름, 없으면 서버 이름 */
export const examStageName = (artwork, examStages, index) =>
  artworkStageFor(artwork, examStages, index)?.name ?? examStages[index]?.label ?? '시험'

/** 서버 { stage, target_minutes }[] ↔ 화면 { key, label, minutes }[] */
export const toTargets = (stages) =>
  stages.map((s) => ({
    key: s.stage,
    label: STAGE_LABELS[s.stage] ?? s.stage,
    minutes: s.target_minutes,
  }))
export const toPlan = (targets) => targets.map((t) => ({ stage: t.key, target_minutes: t.minutes }))

// 예전 버전이 이 기기에만 저장하던 기본 목표 → 처음 한 번 계정으로 옮기고 지움
const LEGACY_KEY = 'artmate.examStageTargets'

function takeLegacyTargets() {
  try {
    const saved = JSON.parse(localStorage.getItem(LEGACY_KEY))
    if (!Array.isArray(saved) || saved.length !== DEFAULT_STAGE_TARGETS.length) return null
    return DEFAULT_STAGE_TARGETS.map((stage, i) => ({
      ...stage,
      minutes: Number(saved[i]?.minutes) || stage.minutes,
    }))
  } catch {
    return null
  }
}

function clearLegacyTargets() {
  try {
    localStorage.removeItem(LEGACY_KEY)
  } catch {
    // 무시
  }
}

/** 내 기본 단계 목표 (계정에 저장, 모든 기기 공통) */
export async function loadExamDefaults() {
  const res = await getExamDefaults()
  if (res.source === 'DEFAULT') {
    const legacy = takeLegacyTargets()
    if (legacy) {
      const saved = await putExamDefaults(toPlan(legacy))
      clearLegacyTargets()
      return toTargets(saved.stages)
    }
  }
  return toTargets(res.stages)
}

export const saveExamDefaults = (targets) => putExamDefaults(toPlan(targets))

export const totalMinutes = (targets) => targets.reduce((sum, t) => sum + t.minutes, 0)

/** 200 → "3시간 20분" */
export function formatMinutes(minutes) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (!h) return `${m}분`
  return m ? `${h}시간 ${m}분` : `${h}시간`
}

// 시험 단계 → 그 단계에서 올리는 작품 사진 단계 (작품 사진은 스케치·중간·완성 3단계)
export const EXAM_PHOTO_STAGE = {
  IDEA: 'SKETCH',
  SKETCH: 'PROGRESS',
  COLOR: 'FINAL',
  FINISH: 'FINAL',
}

/**
 * 서버 단계별 작업 시간(초). ACTIVE 단계는 응답 시점 이후 흐른 시간(liveElapsed − 응답 당시 경과)을 더함
 * liveElapsed: useExamTimer가 1초마다 계산한 전체 경과 초
 */
export function liveStageSeconds(exam, liveElapsed) {
  const base = exam.timer?.elapsed_seconds ?? 0
  return exam.stages.map((s) =>
    s.status === 'ACTIVE' ? s.elapsed_seconds + Math.max(0, liveElapsed - base) : s.elapsed_seconds,
  )
}

/** 메모 작성 시각으로 어느 단계에서 쓴 메모인지 (단계 시작~끝 사이) */
export function stageOfNote(stages, note) {
  const at = Date.parse(note.created_at)
  return (
    stages.find(
      (s) =>
        s.started_at &&
        Date.parse(s.started_at) <= at &&
        (!s.ended_at || at < Date.parse(s.ended_at)),
    )?.stage ?? null
  )
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

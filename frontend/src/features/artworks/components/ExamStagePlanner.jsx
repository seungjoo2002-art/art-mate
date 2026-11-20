import { ChevronDown, ChevronUp, Plus, X } from 'lucide-react'
import { MAX_EXAM_MINUTES, formatMinutes } from '../exam'
import { stageTone } from '../stageTone'
import { MAX_STAGE_NAME, newStageRow } from '../stages'
import styles from './ExamStagePlanner.module.css'

const STEP = 10 // 분
const SLIDER_MAX = 300 // 슬라이더 끝 = 5시간 (한 단계로는 충분)

/**
 * 실기시험 단계와 목표 시간 (실기시험 준비 화면).
 * 위: 원형 시계 = 단계별 시간 비율 + 가운데 총 목표 시간. 아래: 단계마다 이름 · 시간 · 슬라이더(10분 단위)
 * stages: [{ key, id?, name, minutes }] (StageEditor와 같은 모양)
 */
export default function ExamStagePlanner({ stages, onChange, maxStages }) {
  const total = stages.reduce((sum, s) => sum + (s.minutes || 0), 0)

  const patch = (key, values) =>
    onChange(stages.map((s) => (s.key === key ? { ...s, ...values } : s)))
  const move = (index, delta) => {
    const next = [...stages]
    const [row] = next.splice(index, 1)
    next.splice(index + delta, 0, row)
    onChange(next)
  }
  const remove = (key) => onChange(stages.filter((s) => s.key !== key))
  const add = () => onChange([...stages, newStageRow('', { minutes: 30 })])

  /** 슬라이더 값 → 10분 단위, 합계가 서버 제한(24시간)을 넘지 않게 */
  const setMinutes = (stage, value) => {
    const others = total - (stage.minutes || 0)
    const minutes = Math.max(STEP, Math.min(Number(value), MAX_EXAM_MINUTES - others))
    patch(stage.key, { minutes })
  }

  return (
    <div className={styles.planner}>
      <Donut stages={stages} total={total} />

      <ol className={styles.list}>
        {stages.map((stage, index) => {
          const { color } = stageTone(index, stages.length)
          const minutes = stage.minutes || 0
          return (
            <li key={stage.key} className={styles.row} style={{ '--tone': color }}>
              <div className={styles.head}>
                <i className={styles.dot} aria-hidden />
                <input
                  className={styles.name}
                  value={stage.name}
                  maxLength={MAX_STAGE_NAME}
                  placeholder="단계 이름"
                  aria-label={`${index + 1}단계 이름`}
                  onChange={(e) => patch(stage.key, { name: e.target.value })}
                />
                <strong className={styles.time}>{formatMinutes(minutes)}</strong>
                <span className={styles.actions}>
                  <button
                    type="button"
                    onClick={() => move(index, -1)}
                    disabled={index === 0}
                    aria-label={`${index + 1}단계 위로`}
                  >
                    <ChevronUp size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(index, 1)}
                    disabled={index === stages.length - 1}
                    aria-label={`${index + 1}단계 아래로`}
                  >
                    <ChevronDown size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(stage.key)}
                    disabled={stages.length <= 1}
                    aria-label={`${index + 1}단계 삭제`}
                  >
                    <X size={16} />
                  </button>
                </span>
              </div>
              <input
                type="range"
                className={styles.slider}
                min={STEP}
                max={Math.max(SLIDER_MAX, minutes)}
                step={STEP}
                value={minutes}
                aria-label={`${stage.name || `${index + 1}단계`} 목표 시간`}
                aria-valuetext={formatMinutes(minutes)}
                style={{ '--fill': `${(minutes / Math.max(SLIDER_MAX, minutes)) * 100}%` }}
                onChange={(e) => setMinutes(stage, e.target.value)}
              />
            </li>
          )
        })}
      </ol>

      <button
        type="button"
        className={styles.add}
        onClick={add}
        disabled={stages.length >= maxStages}
      >
        <Plus size={16} aria-hidden /> 단계 추가
      </button>
    </div>
  )
}

/** 원형 시계: 단계 시간 비율을 물감 색 고리로, 가운데 총 목표 시간 */
function Donut({ stages, total }) {
  const r = 64
  const circumference = 2 * Math.PI * r
  const gap = stages.length > 1 ? 3 : 0
  // 단계마다 고리 길이와 시작 위치 (앞 단계 길이의 합)
  const lengths = stages.map((s) => (total ? (circumference * (s.minutes || 0)) / total : 0))
  const starts = lengths.map((_, i) => lengths.slice(0, i).reduce((a, b) => a + b, 0))
  return (
    <div className={styles.donut}>
      <svg viewBox="0 0 160 160" role="img" aria-label={`총 목표 시간 ${formatMinutes(total)}`}>
        <circle className={styles.track} cx="80" cy="80" r={r} />
        {stages.map((stage, index) => (
          <circle
            key={stage.key}
            cx="80"
            cy="80"
            r={r}
            className={styles.arc}
            stroke={stageTone(index, stages.length).color}
            strokeDasharray={`${Math.max(0, lengths[index] - gap)} ${circumference}`}
            strokeDashoffset={-starts[index]}
          />
        ))}
      </svg>
      <span className={styles.center} aria-hidden>
        <small>총 목표</small>
        <strong>{formatMinutes(total)}</strong>
      </span>
    </div>
  )
}

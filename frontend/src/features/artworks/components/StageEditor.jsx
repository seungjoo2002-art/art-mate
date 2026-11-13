import { ChevronDown, ChevronUp, Minus, Plus, X } from 'lucide-react'
import { Card } from '../../../components/ui'
import { MAX_EXAM_MINUTES, formatMinutes } from '../exam'
import { MAX_STAGES, MAX_STAGE_NAME, newStageRow } from '../stages'
import styles from './StageEditor.module.css'

const STEP = 10 // 분

/**
 * 작품 제작 단계 편집 (v0.9.7): 추가 · 삭제 · 이름 변경 · 순서 변경
 * withMinutes: 실기시험 모드 → 단계별 목표 시간(10분 단위)과 합계
 * stages: [{ key, id?, name, minutes? }]
 */
export default function StageEditor({
  stages,
  onChange,
  withMinutes = false,
  maxStages = MAX_STAGES,
  title,
  note,
}) {
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
  const add = () => onChange([...stages, newStageRow('', withMinutes ? { minutes: 30 } : {})])

  return (
    <Card className={styles.card}>
      <div className={styles.header}>
        <h2 className={styles.title}>
          {title ?? (withMinutes ? '시험 단계와 목표 시간' : '제작 단계')}
        </h2>
        <span className={styles.count}>
          {stages.length}/{maxStages}
        </span>
      </div>

      <ol className={styles.list}>
        {stages.map((stage, index) => (
          <li key={stage.key} className={styles.row}>
            <span className={styles.step}>{index + 1}</span>
            <div className={styles.main}>
              <input
                className={styles.name}
                value={stage.name}
                maxLength={MAX_STAGE_NAME}
                placeholder="단계 이름 (예: 명암)"
                aria-label={`${index + 1}단계 이름`}
                onChange={(e) => patch(stage.key, { name: e.target.value })}
              />
              {withMinutes && (
                <span className={styles.minutes}>
                  <button
                    type="button"
                    onClick={() =>
                      patch(stage.key, { minutes: Math.max(STEP, (stage.minutes || 0) - STEP) })
                    }
                    disabled={(stage.minutes || 0) <= STEP}
                    aria-label={`${index + 1}단계 ${STEP}분 줄이기`}
                  >
                    <Minus size={14} />
                  </button>
                  <span className={styles.value}>{formatMinutes(stage.minutes || 0)}</span>
                  <button
                    type="button"
                    onClick={() => patch(stage.key, { minutes: (stage.minutes || 0) + STEP })}
                    disabled={total + STEP > MAX_EXAM_MINUTES}
                    aria-label={`${index + 1}단계 ${STEP}분 늘리기`}
                  >
                    <Plus size={14} />
                  </button>
                </span>
              )}
            </div>
            <span className={styles.actions}>
              <button
                type="button"
                onClick={() => move(index, -1)}
                disabled={index === 0}
                aria-label={`${index + 1}단계 위로`}
              >
                <ChevronUp size={18} />
              </button>
              <button
                type="button"
                onClick={() => move(index, 1)}
                disabled={index === stages.length - 1}
                aria-label={`${index + 1}단계 아래로`}
              >
                <ChevronDown size={18} />
              </button>
              <button
                type="button"
                onClick={() => remove(stage.key)}
                disabled={stages.length <= 1}
                aria-label={`${index + 1}단계 삭제`}
              >
                <X size={18} />
              </button>
            </span>
          </li>
        ))}
      </ol>

      <button
        type="button"
        className={styles.add}
        onClick={add}
        disabled={stages.length >= maxStages}
      >
        <Plus size={18} aria-hidden /> 단계 추가
      </button>
      {withMinutes && (
        <div className={styles.total}>
          <span>총 목표 시간</span>
          <span className={styles.value}>{formatMinutes(total)}</span>
        </div>
      )}
      {note && <p className={styles.note}>{note}</p>}
    </Card>
  )
}

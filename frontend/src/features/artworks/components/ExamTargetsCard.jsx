import { useState } from 'react'
import { Minus, Plus, Settings } from 'lucide-react'
import { Card } from '../../../components/ui'
import { MAX_EXAM_MINUTES, formatMinutes, totalMinutes } from '../exam'
import styles from './ExamTargetsCard.module.css'

const STEP = 10 // 분

/** 시험 단계별 목표 시간: 보기 ↔ 수정(10분 단위). 합계가 총 목표 시간 */
export default function ExamTargetsCard({ targets, onChange }) {
  const [editing, setEditing] = useState(false)
  const total = totalMinutes(targets)

  const change = (key, delta) =>
    onChange(
      targets.map((t) =>
        t.key === key ? { ...t, minutes: Math.max(STEP, t.minutes + delta) } : t,
      ),
    )

  return (
    <Card className={styles.card}>
      <div className={styles.header}>
        <h2 className={styles.title}>시험 단계별 목표 시간</h2>
        <button type="button" className={styles.edit} onClick={() => setEditing((v) => !v)}>
          {editing ? (
            '완료'
          ) : (
            <>
              수정 <Settings size={18} aria-hidden />
            </>
          )}
        </button>
      </div>

      {targets.map((t) => (
        <div key={t.key} className={styles.row}>
          <span className={styles.label}>{t.label}</span>
          {editing ? (
            <span className={styles.stepper}>
              <button
                type="button"
                onClick={() => change(t.key, -STEP)}
                disabled={t.minutes <= STEP}
                aria-label={`${t.label} ${STEP}분 줄이기`}
              >
                <Minus size={16} />
              </button>
              <span className={styles.value}>{formatMinutes(t.minutes)}</span>
              <button
                type="button"
                onClick={() => change(t.key, STEP)}
                disabled={total + STEP > MAX_EXAM_MINUTES}
                aria-label={`${t.label} ${STEP}분 늘리기`}
              >
                <Plus size={16} />
              </button>
            </span>
          ) : (
            <span className={styles.value}>{formatMinutes(t.minutes)}</span>
          )}
        </div>
      ))}
      <div className={`${styles.row} ${styles.total}`}>
        <span>총 목표 시간</span>
        <span className={styles.value}>{formatMinutes(total)}</span>
      </div>
    </Card>
  )
}

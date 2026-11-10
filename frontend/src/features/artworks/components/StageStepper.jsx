import { Check } from 'lucide-react'
import styles from './StageStepper.module.css'

/** 단계 진행 표시: 완료된 단계는 체크, 아직이면 번호 */
export default function StageStepper({ stages }) {
  return (
    <ol className={styles.stepper}>
      {stages.map((stage, index) => {
        const done = Boolean(stage.photo)
        return (
          <li key={stage.key} className={`${styles.step} ${done ? styles.done : ''}`}>
            <span className={styles.circle}>{done ? <Check size={20} strokeWidth={3} /> : index + 1}</span>
            <span className={styles.label}>{stage.label}</span>
          </li>
        )
      })}
    </ol>
  )
}

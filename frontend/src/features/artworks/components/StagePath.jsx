import { stageTone } from '../stageTone'
import styles from './StagePath.module.css'

/**
 * 제작 단계를 물감 점으로 이은 길로 보여 줌 (보기 전용, 편집은 StageEditor). 점 색은 stageTone
 * current: 진행 중인 단계 번호(0부터)를 주면 진행 표시 → 지난 단계 ✓, 지금 단계 테두리·크게, 남은 단계 흐리게
 * label: 화면 낭독기용 목록 이름
 */
export default function StagePath({ stages, current, label = '제작 단계' }) {
  const progress = Number.isInteger(current)
  const stateOf = (index) =>
    !progress ? '' : index < current ? styles.done : index === current ? styles.now : styles.later

  return (
    <ol className={styles.path} aria-label={label}>
      {stages.map((stage, index) => (
        <li
          key={stage.key}
          className={`${styles.stop} ${stateOf(index)}`}
          aria-current={progress && index === current ? 'step' : undefined}
        >
          <span
            className={styles.dot}
            style={{
              backgroundColor: stageTone(index, stages.length).color,
              color: stageTone(index, stages.length).textColor,
              // 남은 단계는 흰 막을 덮어 연해지니 글자는 회색 (흰 글자는 안 보임)
              ...(progress && index > current ? { color: 'var(--color-text-sub)' } : {}),
            }}
            aria-hidden
          >
            {progress && index < current ? '✓' : index + 1}
          </span>
          <span className={styles.name}>{stage.name.trim() || `${index + 1}단계`}</span>
        </li>
      ))}
    </ol>
  )
}

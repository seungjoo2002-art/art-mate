import styles from './StagePath.module.css'

/**
 * 제작 단계를 물감 점으로 이은 길로 보여 줌 (보기 전용, 편집은 StageEditor).
 * 점 색: 첫 단계는 연한 주황 → 가운데 주황 → 마지막 단계는 진한 갈주황 (그림이 채워질수록 진해짐)
 */
function stageTone(index, count) {
  const t = count > 1 ? index / (count - 1) : 0.5
  const background =
    t <= 0.5
      ? `color-mix(in srgb, var(--color-primary) ${Math.round(t * 200)}%, var(--color-primary-disabled))`
      : `color-mix(in srgb, var(--color-primary-ink) ${Math.round((t - 0.5) * 200)}%, var(--color-primary))`
  // 진한 쪽(3/4 넘음)만 흰 글자, 나머지는 검정 글자 (둘 다 대비 4.5:1 이상)
  const color = t > 0.75 ? 'var(--color-text-on-dark)' : 'var(--color-text-on-primary)'
  return { backgroundColor: background, color }
}

/**
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
              ...stageTone(index, stages.length),
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

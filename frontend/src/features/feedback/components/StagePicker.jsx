import { useCallback } from 'react'
import { Chip } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { listArtworkStages } from '../api'
import styles from './StagePicker.module.css'

/**
 * 피드백을 붙일 단계 고르기 (v0.9.7). value: 단계 id, '' = 작품 전체 피드백
 * 숨긴 단계는 고를 수 없음 (이미 숨긴 단계에 붙은 피드백이면 그 단계를 그대로 보여 줌)
 */
export default function StagePicker({ artworkId, value, onChange }) {
  const load = useCallback(() => listArtworkStages(artworkId), [artworkId])
  const { data: stages } = useAsync(load)
  if (!stages?.length) return null
  const visible = stages.filter((s) => !s.archived || s.id === value)

  return (
    <div className={styles.field}>
      <span className={styles.label}>어느 단계의 피드백인가요?</span>
      <div className={styles.chips} role="radiogroup" aria-label="피드백 단계">
        <Chip role="radio" aria-checked={!value} selected={!value} onClick={() => onChange('')}>
          작품 전체
        </Chip>
        {visible.map((s) => (
          <Chip
            key={s.id}
            role="radio"
            aria-checked={value === s.id}
            selected={value === s.id}
            onClick={() => onChange(s.id)}
          >
            {s.name}
            {s.archived ? ' (숨김)' : ''}
          </Chip>
        ))}
      </div>
    </div>
  )
}

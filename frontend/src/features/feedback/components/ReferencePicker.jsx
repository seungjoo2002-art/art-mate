import { useCallback } from 'react'
import PhotoChooser from '../../../components/photo/PhotoChooser'
import { Checkbox } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { listArtworkPhotos, listArtworkStages } from '../api'
import { photoTime as time, suggestPhoto } from '../imageRefs'
import styles from './StagePicker.module.css'

/**
 * 피드백 기준 이미지 고르기 (v0.9.8): 이 피드백을 받을 때 실제로 본 작품 사진.
 * value: { photoIds, confirmed, touched } — touched가 아니면 최신 사진을 제안으로 보여 줌.
 * 확인(confirmed)한 연결만 학습 데이터 조건이 된다. 저장 후에도 작품 화면에서 바꿀 수 있다.
 */
export default function ReferencePicker({ artworkId, stageId, value, onChange }) {
  const load = useCallback(
    () => Promise.all([listArtworkPhotos(artworkId), listArtworkStages(artworkId)]),
    [artworkId],
  )
  const { data } = useAsync(load)
  if (!data) return null
  const [photos, stages] = data
  if (!photos.length) return null

  const suggested = suggestPhoto(photos, stageId)
  const selected = value.touched ? value.photoIds : suggested ? [suggested] : []
  const groups = stages
    .filter((s) => !s.archived)
    .map((s) => ({
      key: s.id,
      label: s.name,
      photos: photos
        .filter((p) => p.stage_id === s.id)
        .sort((a, b) => time(a) - time(b))
        .map((p) => ({ id: p.id, url: p.url })),
    }))

  const toggle = (id) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]
    // 직접 고르면 확인한 것으로 본다
    onChange({ photoIds: next, confirmed: true, touched: true })
  }

  return (
    <div className={styles.field}>
      <span className={styles.label}>이 피드백을 받을 때 본 작품 사진</span>
      {!value.touched && suggested && (
        <span className={styles.hint}>가장 최근 사진을 골라 두었어요. 다르면 직접 골라 주세요.</span>
      )}
      <PhotoChooser groups={groups} selected={selected} onToggle={toggle} />
      <Checkbox
        checked={value.confirmed}
        onChange={(checked) =>
          onChange({ photoIds: selected, confirmed: checked, touched: value.touched || checked })
        }
      >
        {selected.length
          ? '고른 사진을 보고 받은 피드백이 맞아요'
          : '사진 없이 받은 피드백이에요'}
      </Checkbox>
    </div>
  )
}

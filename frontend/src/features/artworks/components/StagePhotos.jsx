import { RefreshCw, Trash2 } from 'lucide-react'
import { formatUploadedAt } from '../../../utils/date'
import { photoShownAt } from '../stages'
import PhotoCarousel from './PhotoCarousel'
import styles from './StagePhotos.module.css'

/**
 * 단계 사진 가로 슬라이드 + 지금 보는 사진의 올린 시각 · 교체 · 삭제 (아카이브 상세).
 * 사진이 늘어도 세로 길이는 그대로. 교체·삭제는 지금 보는 사진에.
 * locked: 완성한 작품 (사진 바꾸기 막힘), busy: 이 단계에서 업로드·교체·삭제 중
 */
export default function StagePhotos({
  artworkId,
  photos,
  index,
  onIndexChange,
  stageLabel,
  locked,
  busy,
  onReplace,
  onDelete,
  onOpen,
}) {
  if (!photos.length) return null
  const current = photos[Math.min(index, photos.length - 1)]

  function handleFile(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 파일을 다시 골라도 change가 발생하도록
    if (file) onReplace(current, file)
  }

  return (
    <div className={styles.block} aria-busy={busy}>
      <PhotoCarousel
        artworkId={artworkId}
        photos={photos}
        index={index}
        onIndexChange={onIndexChange}
        alt={`${stageLabel} 사진`}
        onOpen={onOpen}
      />
      <div className={styles.foot}>
        <span className={styles.time}>{formatUploadedAt(photoShownAt(current))}</span>
        {!locked && (
          <span className={styles.actions}>
            {/* 교체: 새 사진을 고른 뒤 확인하고 지금 보는 사진 자리에 넣음 */}
            <label
              className={styles.action}
              aria-label="지금 보는 사진 교체"
              title="사진 교체"
              aria-disabled={busy}
            >
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className={styles.input}
                onChange={handleFile}
                disabled={busy}
              />
              <RefreshCw size={18} aria-hidden />
            </label>
            <button
              type="button"
              className={styles.action}
              onClick={() => onDelete(current)}
              disabled={busy}
              aria-label="지금 보는 사진 삭제"
              title="사진 삭제"
            >
              <Trash2 size={18} aria-hidden />
            </button>
          </span>
        )}
      </div>
    </div>
  )
}

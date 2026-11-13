import { Trash2 } from 'lucide-react'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './ExtraPhotoCard.module.css'

/** 대표 사진이 아닌 추가 사진 (피드백 후 다시 찍은 사진 등). 타임라인에 올린 시각으로 들어감 */
export default function ExtraPhotoCard({ artworkId, photo, stageLabel, locked, busy, onDelete }) {
  return (
    <div className={styles.card}>
      <ArtworkPhoto
        artworkId={artworkId}
        photoId={photo.id}
        url={photo.url}
        alt={`${stageLabel} 추가 사진`}
      />
      <div className={styles.foot}>
        <span className={styles.label}>{stageLabel} · 추가 사진</span>
        {!locked && (
          <button
            type="button"
            className={styles.delete}
            onClick={onDelete}
            disabled={busy}
            aria-label="추가 사진 삭제"
          >
            <Trash2 size={18} />
          </button>
        )}
      </div>
    </div>
  )
}

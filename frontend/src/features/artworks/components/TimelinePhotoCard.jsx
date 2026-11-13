import { Star, Trash2 } from 'lucide-react'
import { formatUploadedAt } from '../../../utils/date'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './TimelinePhotoCard.module.css'

/**
 * 단계 타임라인의 사진 1장 (v0.9.8). 피드백 전후 구분 없이 올린 시각 순으로 쌓인다.
 * 대표 사진은 단계 진행 표시·목록 썸네일에 쓰인다 (아무 사진이나 대표로 지정 가능).
 */
export default function TimelinePhotoCard({
  artworkId,
  photo,
  stageLabel,
  locked,
  busy,
  onMakeRepresentative,
  onDelete,
}) {
  return (
    <div className={styles.card} aria-busy={busy}>
      <ArtworkPhoto
        artworkId={artworkId}
        photoId={photo.id}
        url={photo.url}
        alt={`${stageLabel} 사진`}
        className={styles.image}
      />
      <div className={styles.foot}>
        <span className={styles.label}>
          {photo.is_representative && <span className={styles.badge}>대표</span>}
          {stageLabel} 사진
        </span>
        {!locked && (
          <span className={styles.actions}>
            {!photo.is_representative && (
              <button
                type="button"
                onClick={onMakeRepresentative}
                disabled={busy}
                aria-label={`${formatUploadedAt(photo.uploaded_at ?? photo.created_at)} 사진을 대표로 지정`}
              >
                <Star size={18} />
              </button>
            )}
            <button type="button" onClick={onDelete} disabled={busy} aria-label="사진 삭제">
              <Trash2 size={18} />
            </button>
          </span>
        )}
      </div>
    </div>
  )
}

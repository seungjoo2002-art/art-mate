import { Camera, Check, Upload } from 'lucide-react'
import { formatUploadedAt } from '../../../utils/date'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './StagePhotoCard.module.css'

/** 단계별 사진 카드. 누르면 사진 선택 → onSelectFile(file). 이미 있으면 교체 */
export default function StagePhotoCard({ artworkId, stage, index, uploading, onSelectFile }) {
  const { photo } = stage

  function handleChange(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 파일을 다시 골라도 change가 발생하도록
    if (file) onSelectFile(file)
  }

  return (
    <label className={`${styles.card} ${photo ? styles.filled : styles.empty}`} aria-busy={uploading}>
      <input
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className={styles.input}
        onChange={handleChange}
        disabled={uploading}
      />
      {photo ? (
        <ArtworkPhoto
          key={photo.id}
          artworkId={artworkId}
          photoId={photo.id}
          url={photo.url}
          alt={stage.photoLabel}
          className={styles.thumb}
        />
      ) : (
        <span className={`${styles.thumb} ${styles.placeholder}`}>
          <Camera size={30} aria-hidden />
        </span>
      )}

      <span className={styles.text}>
        <span className={styles.step}>STEP {index + 1}</span>
        <span className={styles.title}>{stage.photoLabel}</span>
        <span className={styles.sub}>
          {uploading
            ? '올리는 중…'
            : photo
              ? `${formatUploadedAt(stage.uploadedAt)} 업로드 · 눌러서 교체`
              : '탭하여 사진 촬영 또는 업로드'}
        </span>
      </span>

      {uploading ? (
        <span className={styles.spinner} aria-hidden />
      ) : photo ? (
        <span className={styles.check}>
          <Check size={22} aria-label="업로드 완료" />
        </span>
      ) : (
        <Upload size={26} aria-hidden />
      )}
    </label>
  )
}

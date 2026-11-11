import { Camera, Check, Trash2, Upload } from 'lucide-react'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './StagePhotoCard.module.css'

/**
 * 단계별 사진 카드. 누르면 사진 선택 → onSelectFile(file). 이미 있으면 교체
 * 사진이 있으면 크게, 없으면 한 줄짜리 업로드 카드
 * 삭제 버튼은 label 밖에 둬서 눌러도 사진 선택창이 열리지 않게 함
 * locked: 완료한 작품 → 보기만 (사진 편집은 서버에서도 409 ARTWORK_COMPLETED)
 */
export default function StagePhotoCard({
  artworkId,
  stage,
  index,
  busy,
  locked = false,
  onSelectFile,
  onDelete,
}) {
  const { photo } = stage

  function handleChange(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 파일을 다시 골라도 change가 발생하도록
    if (file) onSelectFile(file)
  }

  // 완료한 작품은 사진을 고를 수 없으니 label 대신 div
  const Pick = locked ? 'div' : 'label'

  const status = busy ? (
    <span className={styles.spinner} aria-hidden />
  ) : photo ? (
    <span className={styles.check}>
      <Check size={20} aria-label="업로드 완료" />
    </span>
  ) : locked ? null : (
    <Upload size={26} aria-hidden />
  )

  const text = (
    <span className={styles.text}>
      <span className={styles.step}>STEP {index + 1}</span>
      <span className={styles.title}>{stage.photoLabel}</span>
      <span className={styles.sub}>
        {busy
          ? '처리하는 중…'
          : locked
            ? photo
              ? '완료한 작품'
              : '사진 없음'
            : photo
              ? '눌러서 사진 교체'
              : '탭하여 사진 촬영 또는 업로드'}
      </span>
    </span>
  )

  return (
    <div className={`${styles.card} ${photo ? styles.filled : styles.empty}`} aria-busy={busy}>
      <Pick
        className={`${styles.pick} ${photo ? styles.pickFilled : ''} ${locked ? styles.locked : ''}`}
      >
        {!locked && (
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className={styles.input}
            onChange={handleChange}
            disabled={busy}
          />
        )}
        {photo ? (
          <>
            <ArtworkPhoto
              key={photo.id}
              artworkId={artworkId}
              photoId={photo.id}
              url={photo.url}
              alt={stage.photoLabel}
              className={styles.image}
            />
            <span className={styles.row}>
              {text}
              {status}
            </span>
          </>
        ) : (
          <>
            <span className={styles.thumb}>
              <Camera size={30} aria-hidden />
            </span>
            {text}
            {status}
          </>
        )}
      </Pick>

      {photo && !busy && !locked && (
        <button
          type="button"
          className={styles.delete}
          onClick={onDelete}
          aria-label={`${stage.photoLabel} 삭제`}
        >
          <Trash2 size={18} />
        </button>
      )}
    </div>
  )
}

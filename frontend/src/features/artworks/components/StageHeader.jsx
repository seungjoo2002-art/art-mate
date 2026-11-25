import { Camera, ImagePlus } from 'lucide-react'
import styles from './StageHeader.module.css'
import { IMAGE_ACCEPT } from '../../../lib/imageFile'

/**
 * 단계 머리: STEP · 단계 이름 · 사진 수 · 사진 추가. 추가한 사진은 단계 슬라이드 끝에 붙는다
 * (피드백 전후 구분 없음). 아직 사진이 없으면 도화지 모양 업로드 칸.
 */
export default function StageHeader({ stage, index, photoCount, busy, locked, onSelectFile }) {
  function handleChange(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 파일을 다시 골라도 change가 발생하도록
    if (file) onSelectFile(file)
  }

  const input = (
    <input
      type="file"
      accept={IMAGE_ACCEPT}
      className={styles.input}
      onChange={handleChange}
      disabled={busy}
    />
  )

  return (
    <div className={styles.header}>
      <div className={styles.row}>
        <span className={styles.step}>STEP {index + 1}</span>
        <h2 className={styles.title}>{stage.label}</h2>
        <span className={styles.count}>사진 {photoCount}장</span>
        {!locked && photoCount > 0 && (
          <label className={styles.add} aria-busy={busy}>
            {input}
            <ImagePlus size={18} aria-hidden />
            {busy ? '올리는 중…' : '사진 추가'}
          </label>
        )}
      </div>
      {!locked && photoCount === 0 && (
        <label className={styles.empty} aria-busy={busy}>
          {input}
          <span className={styles.emptyIcon}>
            <Camera size={22} aria-hidden />
          </span>
          <span className={styles.emptyTitle}>{busy ? '올리는 중…' : '사진 올리기'}</span>
          <span className={styles.emptySub}>탭해서 촬영하거나 앨범에서 골라요</span>
        </label>
      )}
    </div>
  )
}

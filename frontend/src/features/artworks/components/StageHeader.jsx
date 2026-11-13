import { Camera, ImagePlus } from 'lucide-react'
import styles from './StageHeader.module.css'

/**
 * 단계 타임라인 머리 (v0.9.8): STEP · 단계 이름 · 사진 수 · 사진 추가.
 * 사진은 교체하지 않고 계속 쌓인다 (피드백 전후 구분 없음). 아직 사진이 없으면 큰 업로드 칸.
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
      accept="image/jpeg,image/png,image/webp"
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
          <Camera size={26} aria-hidden />
          <span>{busy ? '올리는 중…' : '탭하여 사진 촬영 또는 업로드'}</span>
        </label>
      )}
    </div>
  )
}

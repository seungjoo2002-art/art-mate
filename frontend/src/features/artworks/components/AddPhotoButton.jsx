import { useEffect, useState } from 'react'
import { ImagePlus } from 'lucide-react'
import { Button, Chip } from '../../../components/ui'
import { STAGES } from '../stages'
import styles from './AddPhotoButton.module.css'

/**
 * 피드백 받은 뒤 고친 사진 등을 "추가"로 올림 (대표 사진은 그대로, 타임라인에 올린 시각으로 들어감)
 * 파일 고르기 → 어느 단계 사진인지 고르기 → 올리기
 */
export default function AddPhotoButton({ defaultStage = 'SKETCH', busy = false, onUpload }) {
  const [picked, setPicked] = useState(null) // { file, preview }
  const [stage, setStage] = useState(defaultStage)
  const file = picked?.file

  // 미리보기 URL은 바뀌거나 사라질 때 해제
  useEffect(() => () => picked && URL.revokeObjectURL(picked.preview), [picked])
  const clear = () => setPicked(null)

  function handleChange(e) {
    const next = e.target.files?.[0]
    e.target.value = ''
    if (!next) return
    setStage(defaultStage)
    setPicked({ file: next, preview: URL.createObjectURL(next) })
  }

  async function handleUpload() {
    const ok = await onUpload(stage, file)
    if (ok !== false) clear()
  }

  if (!file) {
    return (
      <label className={styles.button} aria-busy={busy}>
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className={styles.input}
          onChange={handleChange}
          disabled={busy}
        />
        <ImagePlus size={22} aria-hidden />
        피드백 후 사진 추가
      </label>
    )
  }

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        {picked.preview && <img src={picked.preview} alt="" className={styles.thumb} />}
        <div className={styles.text}>
          <strong>어느 단계 사진인가요?</strong>
          <span>대표 사진은 그대로 두고, 타임라인에 추가돼요.</span>
        </div>
      </div>
      <div className={styles.chips} role="radiogroup" aria-label="사진 단계">
        {STAGES.map((s) => (
          <Chip
            key={s.key}
            role="radio"
            aria-checked={stage === s.key}
            selected={stage === s.key}
            onClick={() => setStage(s.key)}
          >
            {s.label}
          </Chip>
        ))}
      </div>
      <div className={styles.actions}>
        <Button variant="soft" onClick={clear} disabled={busy}>
          취소
        </Button>
        <Button onClick={handleUpload} disabled={busy}>
          {busy ? '올리는 중…' : '사진 올리기'}
        </Button>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { ImagePlus, X } from 'lucide-react'
import { toErrorMessage } from '../../../utils/errorMessages'
import { deletePhoto, uploadStagePhoto } from '../api'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './RevisionPhotos.module.css'

/**
 * 피드백을 반영해 고친 뒤 올린 사진 (v0.9.7). 피드백 카드 바로 아래에 붙는다.
 * feedback: { type: 'NOTE' | 'RECORDING', id }
 * stageId: 피드백의 단계. null(작품 전체 피드백)이면 사진을 올릴 단계를 고른다 (stages)
 * 수정이 잘 됐는지는 판단하지 않고, 어떤 피드백 뒤에 올린 사진인지만 기록한다.
 */
export default function RevisionPhotos({
  artworkId,
  feedback,
  photos,
  stageId,
  stages,
  locked = false,
  label = '피드백 반영 수정 사진',
  onChanged,
}) {
  const choosable = stages.filter((s) => s.id)
  const [target, setTarget] = useState(
    () => stageId ?? [...choosable].reverse().find((s) => s.photo)?.id ?? choosable.at(-1)?.id,
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const uploadStage = stageId ?? target

  async function run(action) {
    setBusy(true)
    setError('')
    try {
      await action()
      onChanged()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function handleFile(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !uploadStage) return
    run(() =>
      uploadStagePhoto(artworkId, uploadStage, file, {
        kind: 'REVISION',
        ...(feedback.type === 'NOTE'
          ? { feedbackNoteId: feedback.id }
          : { feedbackRecordingId: feedback.id }),
      }),
    )
  }

  function handleDelete(photo, index) {
    if (!window.confirm(`수정 사진 ${index + 1}을 삭제할까요?`)) return
    run(() => deletePhoto(artworkId, photo.id))
  }

  if (locked && !photos.length) return null
  const stageName = (id) => stages.find((s) => s.id === id)?.label

  return (
    <div className={styles.box}>
      <span className={styles.label}>
        {label}
        {photos.length ? ` ${photos.length}장` : ''}
      </span>
      {photos.length > 0 && (
        <ol className={styles.grid}>
          {photos.map((photo, index) => (
            <li key={photo.id} className={styles.item}>
              <ArtworkPhoto
                artworkId={artworkId}
                photoId={photo.id}
                url={photo.url}
                alt={`수정 사진 ${index + 1}`}
                className={styles.image}
              />
              <span className={styles.badge}>
                수정 {index + 1}
                {!stageId && stageName(photo.stage_id) ? ` · ${stageName(photo.stage_id)}` : ''}
              </span>
              {!locked && (
                <button
                  type="button"
                  className={styles.delete}
                  onClick={() => handleDelete(photo, index)}
                  disabled={busy}
                  aria-label={`수정 사진 ${index + 1} 삭제`}
                >
                  <X size={14} />
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
      {!locked && (
        <div className={styles.actions}>
          {!stageId && choosable.length > 0 && (
            <select
              className={styles.select}
              value={target ?? ''}
              onChange={(e) => setTarget(e.target.value)}
              aria-label="수정 사진을 올릴 단계"
            >
              {choosable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          )}
          <label className={styles.upload} aria-busy={busy}>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className={styles.input}
              onChange={handleFile}
              disabled={busy || !uploadStage}
            />
            <ImagePlus size={18} aria-hidden />
            {busy ? '처리하는 중…' : '반영 후 사진 올리기'}
          </label>
        </div>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}

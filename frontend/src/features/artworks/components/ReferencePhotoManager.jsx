import { useCallback, useState } from 'react'
import { useAsync } from '../../../hooks/useAsync'
import { prepareImageFiles } from '../../../lib/imageFile'
import { toErrorMessage } from '../../../utils/errorMessages'
import { deleteReferencePhoto, listReferencePhotos } from '../api'
import { acceptFiles, DEFAULT_MAX_REFERENCE_PHOTOS } from '../referencePhotos'
import { useReferenceUploads } from '../useReferenceUploads'
import ReferenceGrid from './ReferenceGrid'
import styles from './ReferenceGrid.module.css'

/**
 * v1.1 기존 작품의 원본 제시물 사진 관리 (작품 수정·상세): 추가·교체·삭제·실패 재시도.
 * 완료한 작품에도 추가할 수 있다 (작업 기록이 아닌 참고 자료). onChanged: 목록이 바뀐 뒤
 */
export default function ReferencePhotoManager({ artworkId, onChanged }) {
  const load = useCallback(() => listReferencePhotos(artworkId), [artworkId])
  const { data, error, reload } = useAsync(load)
  const refresh = useCallback(() => {
    reload()
    onChanged?.()
  }, [reload, onChanged])
  const uploads = useReferenceUploads(refresh)
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState([])

  const max = data?.max_count ?? DEFAULT_MAX_REFERENCE_PHOTOS
  const uploaded = data?.items ?? []

  async function run(action) {
    setBusy(true)
    try {
      await action()
    } finally {
      setBusy(false)
    }
  }

  // 고른 사진을 먼저 준비 (형식 판별, HEIC·HEIF → JPEG) → 미리보기·장수 확인
  async function handleAdd(files) {
    const prepared = await prepareImageFiles(files)
    const pending = uploads.queue.filter((q) => !q.replacesId).length
    const { accepted, rejected } = acceptFiles(prepared.files, max - uploaded.length - pending)
    setMessages([...prepared.rejected, ...rejected].map((r) => `${r.name}: ${r.message}`))
    if (!accepted.length) return
    const items = uploads.add(accepted)
    run(() => uploads.uploadAll(artworkId, items))
  }

  async function handleReplace(photoId, file) {
    const prepared = await prepareImageFiles([file])
    const { accepted, rejected } = acceptFiles(prepared.files, 1)
    setMessages([...prepared.rejected, ...rejected].map((r) => `${r.name}: ${r.message}`))
    if (!accepted.length) return
    const items = uploads.add(accepted, { replacesId: photoId })
    run(() => uploads.uploadAll(artworkId, items))
  }

  async function handleDelete(photo) {
    if (!window.confirm('이 원본 사진을 삭제할까요?')) return
    await run(async () => {
      try {
        await deleteReferencePhoto(artworkId, photo.id)
        refresh()
      } catch (err) {
        setMessages([toErrorMessage(err)])
      }
    })
  }

  if (error) return <p className={styles.error}>{toErrorMessage(error)}</p>
  if (!data) return <p className={styles.hint}>원본 사진을 불러오는 중…</p>

  return (
    <>
      <ReferenceGrid
        uploaded={uploaded}
        queue={uploads.queue}
        max={max}
        disabled={busy}
        onAdd={handleAdd}
        onDelete={handleDelete}
        onReplace={handleReplace}
        onRetry={(item) => run(() => uploads.uploadAll(artworkId, [item]))}
        onRemoveQueued={(item) => uploads.remove(item.key)}
      />
      {messages.map((m) => (
        <p key={m} className={styles.error}>
          {m}
        </p>
      ))}
    </>
  )
}

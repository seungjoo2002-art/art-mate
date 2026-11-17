import { useCallback, useEffect, useRef, useState } from 'react'
import { toErrorMessage } from '../../utils/errorMessages'
import { uploadReferencePhoto } from './api'

let seq = 0

/**
 * v1.1 원본 사진 업로드 대기열. 파일마다 상태(ready·uploading·failed)를 두고 한 장씩 올린다.
 * 실패한 파일은 남겨 두어 다시 시도할 수 있다 (입력 보존). 미리보기는 브라우저 안 URL.
 * onUploaded(photo): 한 장 완료될 때마다 (목록 다시 불러오기 등)
 */
export function useReferenceUploads(onUploaded) {
  const [queue, setQueue] = useState([])
  const queueRef = useRef(queue)

  useEffect(() => {
    queueRef.current = queue
  }, [queue])

  useEffect(() => () => queueRef.current.forEach((item) => URL.revokeObjectURL(item.preview)), [])

  const patch = (key, values) =>
    setQueue((items) => items.map((item) => (item.key === key ? { ...item, ...values } : item)))

  /** 파일을 대기열에 넣는다 (아직 올리지 않음). replacesId: 교체할 원본 사진 */
  const add = useCallback((files, { replacesId } = {}) => {
    const items = files.map((file) => ({
      key: `ref-${++seq}`,
      file,
      preview: URL.createObjectURL(file),
      status: 'ready',
      error: '',
      replacesId: replacesId ?? null,
    }))
    setQueue((current) => [...current, ...items])
    return items
  }, [])

  const remove = useCallback((key) => {
    setQueue((items) => {
      const target = items.find((i) => i.key === key)
      if (target) URL.revokeObjectURL(target.preview)
      return items.filter((i) => i.key !== key)
    })
  }, [])

  /** 대기 중·실패한 파일을 순서대로 올린다. 성공하면 대기열에서 빠진다. 반환: 실패 수 */
  const uploadAll = useCallback(
    async (artworkId, targets = null) => {
      let failed = 0
      const list = (targets ?? queueRef.current).filter((i) => i.status !== 'uploading')
      for (const item of list) {
        patch(item.key, { status: 'uploading', error: '' })
        try {
          const photo = await uploadReferencePhoto(artworkId, item.file, {
            replacesPhotoId: item.replacesId,
          })
          remove(item.key)
          onUploaded?.(photo)
        } catch (err) {
          failed += 1
          patch(item.key, {
            status: 'failed',
            error: err.userMessage ?? toErrorMessage(err),
          })
        }
      }
      return failed
    },
    [onUploaded, remove],
  )

  return { queue, add, remove, uploadAll }
}

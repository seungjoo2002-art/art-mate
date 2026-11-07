import { useEffect, useState } from 'react'
import { getRecordingUrl } from '../api'

/** 비공개 버킷 녹음 재생. Signed URL 만료로 오류가 나면 한 번 새 URL을 받아 재시도 */
export default function RecordingPlayer({ artworkId, recording }) {
  const [freshUrl, setFreshUrl] = useState(null)
  const [retried, setRetried] = useState(false)
  const needsUrl = !recording.url

  useEffect(() => {
    if (!needsUrl) return
    let cancelled = false
    getRecordingUrl(artworkId, recording.id).then(
      (signed) => !cancelled && setFreshUrl(signed.url),
      () => {},
    )
    return () => {
      cancelled = true
    }
  }, [needsUrl, artworkId, recording.id])

  async function handleError() {
    if (retried) return
    setRetried(true)
    try {
      const signed = await getRecordingUrl(artworkId, recording.id)
      setFreshUrl(signed.url)
    } catch {
      // 무시
    }
  }

  const src = freshUrl ?? recording.url
  return <audio controls preload="metadata" src={src ?? undefined} onError={handleError} />
}

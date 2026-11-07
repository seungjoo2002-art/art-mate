import { useEffect, useState } from 'react'
import { getPhotoUrl } from '../api'

/**
 * 비공개 버킷 사진. Signed URL은 몇 분 뒤 만료되므로 로드 실패 시 한 번 새 URL을 받아 재시도
 * url이 없으면(목록 썸네일) 처음에 URL을 받아 옴. 사진이 바뀌면 key로 새로 마운트할 것
 */
export default function ArtworkPhoto({ artworkId, photoId, url, alt = '', className = '' }) {
  const [freshUrl, setFreshUrl] = useState(null)
  const [retried, setRetried] = useState(false)
  const needsUrl = !url

  useEffect(() => {
    if (!needsUrl) return
    let cancelled = false
    getPhotoUrl(artworkId, photoId).then(
      (signed) => !cancelled && setFreshUrl(signed.url),
      () => {}, // 자리 표시 배경만 남김
    )
    return () => {
      cancelled = true
    }
  }, [needsUrl, artworkId, photoId])

  async function handleError() {
    if (retried) return
    setRetried(true)
    try {
      const signed = await getPhotoUrl(artworkId, photoId)
      setFreshUrl(signed.url)
    } catch {
      // 무시
    }
  }

  const src = freshUrl ?? url
  return src ? (
    <img src={src} alt={alt} className={className} onError={handleError} loading="lazy" />
  ) : (
    <span className={className} aria-hidden />
  )
}

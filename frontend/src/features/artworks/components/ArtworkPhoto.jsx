import { useEffect, useState } from 'react'
import { getPhotoUrl } from '../api'

/**
 * 비공개 버킷 사진. Signed URL은 몇 분 뒤 만료되므로 로드 실패 시 한 번 새 URL을 받아 재시도
 * url이 없으면(목록 썸네일) 처음에 URL을 받아 옴. 사진이 바뀌면 key로 새로 마운트할 것
 * loading: 기본 lazy. 가로로 넘기는 칸(overflow 스크롤) 안에서는 사파리가 lazy 사진을 안 불러와서 'eager'
 * fallback(선택): URL을 못 받았거나 재시도 후에도 사진을 못 불러왔을 때 대신 보여 줄 요소
 *   (없으면 예전처럼 빈 자리 표시만)
 */
export default function ArtworkPhoto({
  artworkId,
  photoId,
  url,
  alt = '',
  className = '',
  loading = 'lazy',
  fallback = null,
}) {
  const [freshUrl, setFreshUrl] = useState(null)
  const [retried, setRetried] = useState(false)
  const [failed, setFailed] = useState(false)
  const needsUrl = !url

  useEffect(() => {
    if (!needsUrl) return
    let cancelled = false
    getPhotoUrl(artworkId, photoId).then(
      (signed) => !cancelled && setFreshUrl(signed.url),
      () => !cancelled && setFailed(true),
    )
    return () => {
      cancelled = true
    }
  }, [needsUrl, artworkId, photoId])

  async function handleError() {
    if (retried) {
      setFailed(true)
      return
    }
    setRetried(true)
    try {
      const signed = await getPhotoUrl(artworkId, photoId)
      setFreshUrl(signed.url)
    } catch {
      setFailed(true)
    }
  }

  if (failed && fallback) return fallback
  const src = freshUrl ?? url
  return src ? (
    <img src={src} alt={alt} className={className} onError={handleError} loading={loading} />
  ) : (
    <span className={className} aria-hidden />
  )
}

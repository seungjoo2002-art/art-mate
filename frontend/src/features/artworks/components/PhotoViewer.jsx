import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './PhotoViewer.module.css'

/**
 * 사진 크게 보기: 화면 가득 검은 바탕에 원래 비율 그대로. 바탕·닫기·Esc로 닫음.
 * photo: { id, url } (null이면 닫힘)
 */
export default function PhotoViewer({ artworkId, photo, alt = '', caption, onClose }) {
  useEffect(() => {
    if (!photo) return undefined
    const onKey = (e) => e.key === 'Escape' && onClose()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = overflow
      window.removeEventListener('keydown', onKey)
    }
  }, [photo, onClose])

  if (!photo) return null
  return createPortal(
    <div className={styles.backdrop} role="dialog" aria-modal="true" aria-label={alt} onClick={onClose}>
      <button type="button" className={styles.close} onClick={onClose} aria-label="닫기" autoFocus>
        <X size={24} aria-hidden />
      </button>
      <ArtworkPhoto
        key={photo.id}
        artworkId={artworkId}
        photoId={photo.id}
        url={photo.url}
        alt={alt}
        className={styles.image}
        loading="eager"
      />
      {caption && <p className={styles.caption}>{caption}</p>}
    </div>,
    document.body,
  )
}

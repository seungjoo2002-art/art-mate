import { Link } from 'react-router-dom'
import mascotStanding from '../../../assets/mascot/mascot-standing.webp'
import { isCompleted } from '../stages'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './GalleryStrip.module.css'

/**
 * 액자에 건 작품 줄 (홈, 실기 탭의 최근 작품). 옆으로 넘겨 봄.
 * 고양이가 두 번째 액자 뒤에서 빼꼼 (작품이 하나면 첫 번째 뒤)
 */
export default function GalleryStrip({ artworks }) {
  const peekAt = artworks.length > 1 ? 1 : 0

  return (
    <div className={styles.strip}>
      {artworks.map((a, i) => (
        <Link key={a.id} to={`/artworks/${a.id}`} className={styles.item}>
          {i === peekAt && <img className={styles.cat} src={mascotStanding} alt="" />}
          <span className={styles.frame}>
            {a.cover_photo_id ? (
              <ArtworkPhoto
                artworkId={a.id}
                photoId={a.cover_photo_id}
                alt={a.title}
                className={styles.photo}
                loading="eager" // 가로 스크롤 칸 안이라 lazy면 사파리에서 안 뜸 (최대 4장)
              />
            ) : (
              <span className={styles.photo} aria-hidden />
            )}
          </span>
          <strong className={styles.title}>{a.title}</strong>
          <small className={styles.meta}>{isCompleted(a) ? '완성' : '진행 중'}</small>
        </Link>
      ))}
    </div>
  )
}

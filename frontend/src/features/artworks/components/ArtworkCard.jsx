import { Link } from 'react-router-dom'
import { Badge } from '../../../components/ui'
import { formatMonthDay } from '../../../utils/date'
import { isCompleted } from '../stages'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './ArtworkCard.module.css'

/** 아카이브 그리드의 작품 카드 */
export default function ArtworkCard({ artwork }) {
  return (
    <Link to={`/artworks/${artwork.id}`} className={styles.card}>
      <span className={styles.cover}>
        {artwork.cover_photo_id ? (
          <ArtworkPhoto
            artworkId={artwork.id}
            photoId={artwork.cover_photo_id}
            alt={artwork.title}
            className={styles.image}
          />
        ) : (
          <span className={styles.image} aria-hidden />
        )}
        <Badge variant="overlay" className={styles.badge}>
          {isCompleted(artwork) ? '완성' : '진행 중'}
        </Badge>
      </span>
      <span className={styles.title}>{artwork.title}</span>
      <span className={styles.meta}>
        {formatMonthDay(artwork.work_date)} · 사진 {artwork.photo_count}
      </span>
    </Link>
  )
}

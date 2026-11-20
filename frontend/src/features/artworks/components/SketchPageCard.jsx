import { formatMonthDay } from '../../../utils/date'
import { typeColor } from '../practicalTypes'
import { isCompleted } from '../stages'
import ArtworkPhoto from './ArtworkPhoto'
import SketchPage from './SketchPage'
import styles from './SketchPage.module.css'

/** 아카이브 전체 기록 카드: 뜯어낸 스케치북 한 장 + 실기 유형 색 클립 + 제목 · 상태 · 날짜 */
export default function SketchPageCard({ artwork }) {
  const done = isCompleted(artwork)
  return (
    <SketchPage
      to={`/artworks/${artwork.id}`}
      seed={artwork.id}
      accent={typeColor(artwork.practical_type)}
      media={
        artwork.cover_photo_id ? (
          <ArtworkPhoto
            artworkId={artwork.id}
            photoId={artwork.cover_photo_id}
            alt={artwork.title}
            className={styles.photo}
          />
        ) : (
          <span className={styles.photo} aria-hidden />
        )
      }
      date={formatMonthDay(artwork.work_date)}
      title={artwork.title}
      footer={
        <span className={`${styles.status} ${done ? styles.done : ''}`}>
          {done ? '완성' : '진행 중'}
        </span>
      }
    />
  )
}

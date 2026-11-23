import { ImageOff, ImagePlus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatMonthDay } from '../../../utils/date'
import { artworkCardView } from '../archiveView'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './ArtworkCard.module.css'

/**
 * 작품 카드 (폴라로이드): 사진을 크게, 아래 여백에 제목 · 날짜 · 상태.
 * 아카이브 목록(variant="grid")과 홈·실기 탭 최근 작품 줄(variant="strip")이 같은 모양을 쓴다.
 * typeLabel(선택): 실기 유형 (기초디자인 등) — 분류가 아닌 보조 정보로 작게
 * eager: 가로로 넘기는 칸 안에서는 사파리가 lazy 사진을 안 불러와서 true
 */
export default function ArtworkCard({ artwork, variant = 'grid', typeLabel, eager = false }) {
  const view = artworkCardView(artwork)
  return (
    <Link to={`/artworks/${artwork.id}`} className={`${styles.card} ${styles[variant]}`}>
      <span className={styles.photoBox}>
        {view.hasPhoto ? (
          <ArtworkPhoto
            artworkId={artwork.id}
            photoId={artwork.cover_photo_id}
            alt={artwork.title}
            className={styles.photo}
            loading={eager ? 'eager' : 'lazy'}
            fallback={<EmptyPhoto failed />}
          />
        ) : (
          <EmptyPhoto hint={variant === 'grid' ? view.emptyHint : null} />
        )}
      </span>
      <span className={styles.caption}>
        <strong className={styles.title}>{artwork.title}</strong>
        <span className={styles.meta}>
          {artwork.work_date && <span>{formatMonthDay(artwork.work_date)}</span>}
          <span className={view.done ? styles.done : styles.doing}>{view.status}</span>
        </span>
        {(view.exam || typeLabel) && (
          <span className={styles.tags}>
            {view.exam && <span className={styles.tag}>실기시험</span>}
            {typeLabel && <span className={styles.tagSoft}>{typeLabel}</span>}
          </span>
        )}
      </span>
    </Link>
  )
}

/** 사진 자리: 회색 상자 대신 미색 종이 + 작은 아이콘. 로드 실패와 미등록을 구분 */
function EmptyPhoto({ failed = false, hint = null }) {
  const Icon = failed ? ImageOff : ImagePlus
  return (
    <span className={styles.empty}>
      <Icon size={22} strokeWidth={1.6} aria-hidden />
      <span className={styles.emptyText}>
        {failed ? '사진을 불러오지 못했어요' : '아직 사진이 없어요'}
      </span>
      {!failed && hint && <span className={styles.emptyHint}>{hint}</span>}
    </span>
  )
}

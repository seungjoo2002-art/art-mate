import { Mic, PenLine } from 'lucide-react'
import { Link } from 'react-router-dom'
import styles from './FeedbackTimeline.module.css'

/**
 * 녹음·글 첨삭 등록 아이콘 (글자 없이도 알아봄. 화면 낭독기·툴팁에는 이름을 줌).
 * stageId: 단계 피드백 (없으면 작품 전체), photoId: 기본 기준 사진 (지금 슬라이드에서 보는 사진)
 */
export default function AddFeedbackButtons({ artworkId, stageId, photoId, compact = false }) {
  const params = new URLSearchParams()
  if (stageId) params.set('stage', stageId)
  if (photoId) params.set('photo', photoId)
  const query = params.toString() ? `?${params}` : ''
  return (
    <div className={`${styles.buttons} ${compact ? styles.compact : ''}`}>
      <Link
        to={`/artworks/${artworkId}/recordings/new${query}`}
        className={`${styles.recordButton} ${styles.iconOnly}`}
        aria-label="피드백 녹음"
        title="피드백 녹음"
      >
        <Mic size={compact ? 16 : 18} aria-hidden />
      </Link>
      <Link
        to={`/artworks/${artworkId}/notes/new${query}`}
        className={`${styles.recordButton} ${styles.iconOnly}`}
        aria-label="글로 첨삭 남기기"
        title="글로 첨삭 남기기"
      >
        <PenLine size={compact ? 16 : 18} aria-hidden />
      </Link>
    </div>
  )
}

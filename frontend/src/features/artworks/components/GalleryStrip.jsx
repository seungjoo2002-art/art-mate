import mascotStanding from '../../../assets/mascot/mascot-standing.webp'
import ArtworkCard from './ArtworkCard'
import styles from './GalleryStrip.module.css'

/**
 * 최근 작품 줄 (홈, 실기 탭). 아카이브와 같은 폴라로이드 카드를 옆으로 넘겨 봄.
 * 고양이가 두 번째 카드 뒤에서 빼꼼 (작품이 하나면 첫 번째 뒤)
 */
export default function GalleryStrip({ artworks }) {
  const peekAt = artworks.length > 1 ? 1 : 0

  return (
    <div className={styles.strip}>
      {artworks.map((a, i) => (
        <div key={a.id} className={styles.item}>
          {i === peekAt && <img className={styles.cat} src={mascotStanding} alt="" />}
          {/* 가로 스크롤 칸 안이라 lazy면 사파리에서 안 뜸 (최대 4장) */}
          <ArtworkCard artwork={a} variant="strip" eager />
        </div>
      ))}
    </div>
  )
}

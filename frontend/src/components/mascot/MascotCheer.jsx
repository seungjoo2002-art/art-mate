import mascotStanding from '../../assets/mascot/mascot-standing.webp'
import styles from './MascotCheer.module.css'

/**
 * 서 있는 고양이 + 말풍선 응원 (작품 상세, 실기시험 진행).
 * children: 말풍선 굵은 한 줄, sub: 그 아래 작은 글자 (선택)
 */
export default function MascotCheer({ children, sub }) {
  return (
    <div className={styles.hero}>
      <img className={styles.cat} src={mascotStanding} alt="" />
      <div className={styles.bubble}>
        <p className={styles.cheer}>{children}</p>
        {sub && <p className={styles.sub}>{sub}</p>}
      </div>
    </div>
  )
}

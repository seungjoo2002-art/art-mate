import { MASCOT_POSES } from './poses'
import styles from './MascotCheer.module.css'

/**
 * 고양이 + 말풍선 응원 (홈, 작품 상세, 실기시험 진행·결과, 분석 리포트, 빈 아카이브, 404).
 * children: 말풍선 굵은 한 줄, eyebrow: 그 위 작은 글자, sub: 그 아래 작은 글자 (둘 다 선택)
 * as: 굵은 줄 태그 (홈에서는 화면 제목이라 'h1'), size: 'lg'면 고양이·말풍선 크게 (홈)
 * pose: 고양이 표정·자세 (poses.js, 기본 standing)
 */
export default function MascotCheer({ children, eyebrow, sub, as: Title = 'p', size, pose = 'standing' }) {
  return (
    <div className={`${styles.hero} ${size === 'lg' ? styles.lg : ''}`}>
      <img className={styles.cat} src={MASCOT_POSES[pose] ?? MASCOT_POSES.standing} alt="" />
      <div className={styles.bubble}>
        {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
        <Title className={styles.cheer}>{children}</Title>
        {sub && <p className={styles.sub}>{sub}</p>}
      </div>
    </div>
  )
}

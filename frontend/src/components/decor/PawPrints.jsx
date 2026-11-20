import styles from './Decor.module.css'

/** 고양이 발자국 하나 (발바닥 + 발가락 네 개) */
function Paw({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden focusable="false">
      <ellipse cx="12" cy="16" rx="5.2" ry="4.4" />
      <ellipse cx="5.6" cy="10.4" rx="2.1" ry="2.6" transform="rotate(-18 5.6 10.4)" />
      <ellipse cx="9.6" cy="6.6" rx="2.1" ry="2.7" transform="rotate(-6 9.6 6.6)" />
      <ellipse cx="14.4" cy="6.6" rx="2.1" ry="2.7" transform="rotate(6 14.4 6.6)" />
      <ellipse cx="18.4" cy="10.4" rx="2.1" ry="2.6" transform="rotate(18 18.4 10.4)" />
    </svg>
  )
}

/** 제목 옆 꾸밈: 고양이가 지나간 발자국 두 개 (주황, 하나는 연하게). 화면 낭독기는 건너뜀 */
export default function PawPrints() {
  return (
    <span className={styles.paws} aria-hidden>
      <Paw className={styles.paw} />
      <Paw className={`${styles.paw} ${styles.pawNext}`} />
    </span>
  )
}

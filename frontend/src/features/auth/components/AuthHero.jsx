import styles from './AuthHero.module.css'

/** 로그인·회원가입 상단: 주황 로고(visual을 주면 대신 표시, null이면 없음) + 제목 + 설명 (가운데 정렬) */
export default function AuthHero({ title, description, large = false, visual }) {
  return (
    <div className={styles.hero}>
      {visual === undefined ? (
        <span className={styles.logo} aria-hidden>
          A
        </span>
      ) : (
        visual
      )}
      <h1 className={`${styles.title} ${large ? styles.large : ''}`}>{title}</h1>
      {description && <p className={styles.description}>{description}</p>}
    </div>
  )
}

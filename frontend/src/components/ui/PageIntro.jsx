import styles from './PageIntro.module.css'

/** 화면 상단 소개 블록: 주황 eyebrow + 큰 제목 + 설명 */
export default function PageIntro({ eyebrow, title, description, action }) {
  return (
    <header className={styles.intro}>
      <div className={styles.text}>
        {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
        <h1 className={styles.title}>{title}</h1>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      {action}
    </header>
  )
}

import styles from './Decor.module.css'

/** 문장의 핵심 말 아래 주황 붓 형광펜 (랜딩 ART MATE 아래 붓 자국과 같은 느낌) */
export default function Highlight({ children }) {
  return <span className={styles.highlight}>{children}</span>
}

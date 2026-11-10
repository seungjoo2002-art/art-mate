import styles from './BottomCta.module.css'

/** 화면 하단에 고정되는 버튼 영역 (유형 선택의 "다음" 등) */
export default function BottomCta({ children }) {
  return <div className={styles.cta}>{children}</div>
}

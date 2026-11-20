import styles from './Decor.module.css'

/** 문장 끝 주황 물감 튄 자국 (이모지 대신). 꾸밈이라 화면 낭독기는 건너뜀 */
export default function PaintSplash() {
  return (
    <svg className={styles.splash} viewBox="0 0 40 40" aria-hidden focusable="false">
      <path d="M20 6c4 0 5 4 8 5s7-1 7 3-4 4-4 7 4 6 1 8-6-1-8 1-2 6-5 6-3-4-6-5-7 1-7-3 4-4 3-7-5-5-2-8 6 0 8-2 1-5 5-5z" />
      <circle cx="34" cy="31" r="2.2" />
      <circle cx="6" cy="9" r="1.6" />
    </svg>
  )
}

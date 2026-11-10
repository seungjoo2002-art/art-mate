import styles from './FullScreenStatus.module.css'

/** 로딩·오류·안내용 전체 화면. title이 없으면 로딩 스피너만 표시 */
export default function FullScreenStatus({ title, description, children }) {
  return (
    <main className={styles.screen} aria-busy={!title}>
      {title ? (
        <>
          <h1 className={styles.title}>{title}</h1>
          {description && <p className={styles.description}>{description}</p>}
          {children && <div className={styles.actions}>{children}</div>}
        </>
      ) : (
        <span className={styles.spinner} role="status" aria-label="불러오는 중" />
      )}
    </main>
  )
}

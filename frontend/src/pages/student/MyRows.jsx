import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import styles from './MyPage.module.css'

/** 작은 회색 제목 + 흰 묶음 목록 (설정 앱처럼). 제목 없이도 씀 */
export function Group({ title, children }) {
  return (
    <section className={styles.group}>
      {title && <h2 className={styles.groupTitle}>{title}</h2>}
      <div className={styles.list}>{children}</div>
    </section>
  )
}

/** 목록 한 줄: 아이콘 · 이름 · 값 · › (to가 있으면 누르면 이동) */
export function Row({ to, icon: Icon, label, value, danger = false, onClick }) {
  const body = (
    <>
      <span className={`${styles.icon} ${danger ? styles.iconDanger : ''}`}>
        <Icon size={17} aria-hidden />
      </span>
      <span className={`${styles.rowLabel} ${danger ? styles.danger : ''}`}>{label}</span>
      {value !== undefined && (
        <span className={`${styles.rowValue} ${value ? '' : styles.unset}`}>
          {value || '미설정'}
        </span>
      )}
      {to && <ChevronRight size={18} className={styles.chevron} aria-hidden />}
    </>
  )
  if (to) {
    return (
      <Link to={to} className={styles.row}>
        {body}
      </Link>
    )
  }
  if (onClick) {
    return (
      <button type="button" className={styles.row} onClick={onClick}>
        {body}
      </button>
    )
  }
  return <div className={styles.row}>{body}</div>
}

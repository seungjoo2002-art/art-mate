import { ChevronLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import styles from './TopBar.module.css'

/** 온보딩 등 단계형 화면 상단: 뒤로가기 + 제목 + 단계 표시(예: "1 / 2") */
export default function TopBar({ title, step }) {
  const navigate = useNavigate()

  return (
    <header className={styles.bar}>
      <button type="button" className={styles.back} onClick={() => navigate(-1)} aria-label="뒤로">
        <ChevronLeft size={28} />
      </button>
      <h1 className={styles.title}>{title}</h1>
      <span className={styles.step}>{step}</span>
    </header>
  )
}

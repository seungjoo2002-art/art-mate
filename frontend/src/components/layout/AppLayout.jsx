import { Outlet } from 'react-router-dom'
import AppHeader from './AppHeader'
import BottomNav from './BottomNav'
import styles from './AppLayout.module.css'

/** 로그인 후 탭 화면 공통 레이아웃: 상단 로고 헤더 + 하단 탭바 */
export default function AppLayout() {
  return (
    <>
      <AppHeader />
      <main className={styles.main}>
        <Outlet />
      </main>
      <BottomNav />
    </>
  )
}

import { Outlet } from 'react-router-dom'
import AppHeader from './AppHeader'

/** 탭 안의 하위 화면 (작품 제작 등): 로고 헤더만 있고 하단 탭바 없음. 각 화면이 TopBar를 그림 */
export default function SubLayout() {
  return (
    <>
      <AppHeader />
      <Outlet />
    </>
  )
}

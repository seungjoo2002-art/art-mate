import { Link, Outlet, useOutletContext } from 'react-router-dom'
import styles from './Instructor.module.css'

/**
 * /instructor/academies/:academyId/* 공통: 내가 강사 이상으로 소속된 운영 중 학원일 때만 하위 화면.
 * (서버도 소속·역할로 다시 검사: 소속이 아니면 404, 역할 부족이면 403)
 */
export default function AcademyScope() {
  const context = useOutletContext()
  if (!context.academy) {
    return (
      <div className={styles.empty}>
        <p>이 학원의 강사 화면을 열 수 없어요. 소속·승인 상태를 확인해 주세요.</p>
        <p>
          <Link to="/instructor/start" className={styles.link}>
            학원 등록·소속 신청으로 가기
          </Link>
        </p>
      </div>
    )
  }
  return <Outlet context={context} />
}

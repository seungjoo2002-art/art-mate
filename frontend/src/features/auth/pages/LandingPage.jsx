import { TrendingUp } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/ui'
import styles from './LandingPage.module.css'

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <main className={styles.page}>
      <div className={styles.hero} aria-hidden>
        <span className={`${styles.dot} ${styles.dotOrange}`} />
        <span className={`${styles.dot} ${styles.dotBrown}`} />
        {/* TODO: 디자인 사진 받으면 src/assets/landing/ 에 넣고 <img>로 교체 */}
        <div className={styles.arch} />
        <div className={styles.photo} />
        <div className={styles.floating}>
          <TrendingUp size={26} />
          <div>
            <p className={styles.floatingTitle}>성장 기록</p>
            <p className={styles.floatingSub}>이번 달 작품 8개</p>
          </div>
        </div>
      </div>

      <section className={styles.content}>
        <p className={styles.eyebrow}>ART MATE</p>
        <h1 className={styles.title}>
          기록하는 모든 순간이
          <br />
          성장으로 이어지도록.
        </h1>
        <p className={styles.description}>
          학생의 작품 제작 과정과 선생님의 피드백을 연결하는 미술입시 성장 관리 플랫폼입니다.
        </p>
        <Button withArrow onClick={() => navigate('/signup')}>
          시작하기
        </Button>
        <p className={styles.login}>
          이미 계정이 있으신가요?
          <Link to="/login" className={styles.loginLink}>
            로그인
          </Link>
        </p>
      </section>
    </main>
  )
}

import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/ui'
import AuthHero from '../components/AuthHero'
import styles from './AuthForm.module.css'

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className={styles.page}>
      <main className={`${styles.body} ${styles.landing}`}>
        <AuthHero
          large
          title="ART MATE"
          description={'작품을 기록하고, 피드백을 모으고\n나의 성장을 확인하세요.'}
        />
        <div className={styles.landingActions}>
          <Button onClick={() => navigate('/login')}>시작하기</Button>
          <Link to="/signup" className={styles.switch}>
            처음 이용하시나요? 회원가입
          </Link>
        </div>
      </main>
    </div>
  )
}

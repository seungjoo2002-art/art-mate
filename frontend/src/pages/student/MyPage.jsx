import { LogOut } from 'lucide-react'
import { useAuth } from '../../app/providers/AuthContext'
import { Card, PageIntro } from '../../components/ui'
import styles from './MyPage.module.css'

export default function MyPage() {
  const { profile, signOut } = useAuth()

  return (
    <>
      <PageIntro
        eyebrow="MY ART MATE"
        title="나의 프로필"
        description="나만의 성장 목표와 설정을 관리해요."
      />

      <Card variant="dark" className={styles.profile}>
        <span className={styles.avatar}>{profile.display_name.slice(0, 1)}</span>
        <div>
          <p className={styles.name}>{profile.display_name}</p>
          <p className={styles.email}>{profile.email}</p>
        </div>
      </Card>

      <Card className={styles.menu}>
        <button type="button" className={styles.logout} onClick={signOut}>
          로그아웃
          <LogOut size={22} aria-hidden />
        </button>
      </Card>
    </>
  )
}

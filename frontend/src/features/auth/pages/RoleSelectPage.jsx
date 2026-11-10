import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import BottomCta from '../../../components/layout/BottomCta'
import TopBar from '../../../components/layout/TopBar'
import { Button, PageIntro } from '../../../components/ui'
import RoleOption from '../components/RoleOption'
import { ROLES } from '../roles'
import styles from './AuthForm.module.css'

export default function RoleSelectPage() {
  const navigate = useNavigate()
  const [role, setRole] = useState(null)

  return (
    <div className={styles.page}>
      <TopBar title="사용자 유형 선택" step="1 / 2" />
      <main className={styles.body}>
        <PageIntro
          eyebrow="WELCOME TO ART MATE"
          title={'어떤 목적으로\n이용하시나요?'}
          description="선택한 유형에 맞는 성장 경험을 준비해 드릴게요."
        />
        <div className={styles.options} role="radiogroup" aria-label="사용자 유형">
          {Object.keys(ROLES).map((key) => (
            <RoleOption key={key} role={key} selected={role === key} onSelect={setRole} />
          ))}
        </div>
      </main>
      <BottomCta>
        <Button withArrow disabled={!role} onClick={() => navigate('/signup', { state: { role } })}>
          다음
        </Button>
      </BottomCta>
    </div>
  )
}

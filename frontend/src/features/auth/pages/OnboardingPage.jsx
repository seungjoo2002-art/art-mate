import { useState } from 'react'
import { User } from 'lucide-react'
import { Navigate } from 'react-router-dom'
import AuthStatusScreen from '../../../app/AuthStatusScreen'
import { useAuth } from '../../../app/providers/AuthContext'
import BottomCta from '../../../components/layout/BottomCta'
import TopBar from '../../../components/layout/TopBar'
import { Button, Input, PageIntro } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import styles from './AuthForm.module.css'

/** 로그인은 됐지만 프로필이 없는 경우 (가입 도중 이탈, 다른 브라우저에서 메일 인증 등) */
export default function OnboardingPage() {
  const { status, createProfile } = useAuth()
  const [displayName, setDisplayName] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (status === 'ready') return <Navigate to="/home" replace />
  if (status === 'signedOut') return <Navigate to="/" replace />
  if (status !== 'needsProfile') return <AuthStatusScreen />

  const name = displayName.trim()

  async function handleSubmit() {
    setSubmitting(true)
    setFormError('')
    try {
      await createProfile({ displayName: name })
    } catch (error) {
      setFormError(toErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.page}>
      <TopBar title="프로필 설정" />
      <main className={styles.body}>
        <PageIntro
          eyebrow="WELCOME TO ART MATE"
          title="가입을 마무리할게요"
          description="사용할 이름이나 닉네임을 알려 주세요."
        />
        <Input
          label="이름 또는 닉네임"
          icon={User}
          placeholder="김서연"
          maxLength={50}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
        {formError && <p className={styles.formError}>{formError}</p>}
      </main>
      <BottomCta>
        <Button disabled={!name || submitting} onClick={handleSubmit}>
          {submitting ? '저장하는 중…' : '시작하기'}
        </Button>
      </BottomCta>
    </div>
  )
}

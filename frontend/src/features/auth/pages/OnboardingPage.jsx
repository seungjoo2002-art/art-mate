import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import AuthStatusScreen from '../../../app/AuthStatusScreen'
import { useAuth } from '../../../app/providers/AuthContext'
import { Button, Input } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import AuthHero from '../components/AuthHero'
import styles from './AuthForm.module.css'

/** 로그인은 됐지만 프로필이 없는 경우 (가입 도중 이탈, 다른 브라우저에서 메일 인증 등) */
export default function OnboardingPage() {
  const { status, createProfile } = useAuth()
  const [displayName, setDisplayName] = useState('')
  const [realName, setRealName] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (status === 'ready') return <Navigate to="/home" replace />
  if (status === 'signedOut') return <Navigate to="/" replace />
  if (status !== 'needsProfile') return <AuthStatusScreen />

  const name = displayName.trim()

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name) return
    setSubmitting(true)
    setFormError('')
    try {
      await createProfile({ displayName: name, realName: realName.trim() || undefined })
    } catch (error) {
      setFormError(toErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.page}>
      <main className={styles.body}>
        <AuthHero
          title="가입을 마무리할게요"
          description="다른 사람에게 보일 닉네임을 알려 주세요."
        />
        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <Input
            label="공개 닉네임"
            placeholder="서연의작업실"
            maxLength={50}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <Input
            label="이름 (선택)"
            placeholder="김서연"
            autoComplete="name"
            maxLength={50}
            value={realName}
            onChange={(e) => setRealName(e.target.value)}
          />
          <p className={styles.hint}>이름은 나만 볼 수 있어요.</p>
          {formError && <p className={styles.formError}>{formError}</p>}
          <Button type="submit" disabled={!name || submitting}>
            {submitting ? '저장하는 중…' : '다음'}
          </Button>
        </form>
      </main>
    </div>
  )
}

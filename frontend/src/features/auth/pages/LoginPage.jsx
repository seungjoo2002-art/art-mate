import { useState } from 'react'
import { Lock, Mail } from 'lucide-react'
import { Link } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Button, Input, PageIntro } from '../../../components/ui'
import { supabase } from '../../../lib/supabase'
import { toErrorMessage } from '../../../utils/errorMessages'
import styles from './AuthForm.module.css'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!email.trim() || !password) {
      setFormError('이메일과 비밀번호를 입력해 주세요.')
      return
    }
    setSubmitting(true)
    setFormError('')
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
    setSubmitting(false)
    // 성공하면 AuthProvider 상태가 바뀌고 가드가 홈으로 보내 줌
    if (error) setFormError(toErrorMessage(error))
  }

  return (
    <div className={styles.page}>
      <TopBar title="로그인" />
      <main className={styles.body}>
        <PageIntro
          eyebrow="WELCOME BACK"
          title="다시 만나서 반가워요"
          description="오늘의 기록을 이어가 볼까요?"
        />
        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <Input
            label="이메일"
            icon={Mail}
            type="email"
            placeholder="name@example.com"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            label="비밀번호"
            icon={Lock}
            type="password"
            placeholder="비밀번호 입력"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {formError && <p className={styles.formError}>{formError}</p>}
          <Button type="submit" disabled={submitting}>
            {submitting ? '로그인 중…' : '로그인'}
          </Button>
        </form>
        <p className={styles.footer}>
          아직 계정이 없으신가요?
          <Link to="/signup/role" className={styles.link}>
            회원가입
          </Link>
        </p>
      </main>
    </div>
  )
}

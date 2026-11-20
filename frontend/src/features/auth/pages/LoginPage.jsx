import { useState } from 'react'
import { Link } from 'react-router-dom'
import mascotStanding from '../../../assets/mascot/mascot-standing.webp'
import TopBar from '../../../components/layout/TopBar'
import Highlight from '../../../components/decor/Highlight'
import PaintSplash from '../../../components/decor/PaintSplash'
import { Button, Input } from '../../../components/ui'
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
      <TopBar title="로그인" plain />
      <main className={styles.body}>
        <header className={styles.intro}>
          <h1 className={styles.introTitle}>
            {'다시 만나서\n'}
            <Highlight>반갑습니다</Highlight>
            <PaintSplash />
          </h1>
          <p className={styles.introText}>미술 입시 학습 기록을 한곳에서 관리해 보세요.</p>
        </header>
        <div className={styles.cardWrap}>
          <img className={styles.peek} src={mascotStanding} alt="" />
          <form className={`${styles.form} ${styles.formCard}`} onSubmit={handleSubmit} noValidate>
            <Input
              label="이메일"
              type="email"
              placeholder="student@example.com"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Input
              label="비밀번호"
              type="password"
              placeholder="비밀번호 입력"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {formError && <p className={styles.formError}>{formError}</p>}
            <Button type="submit" size="compact" disabled={submitting}>
              {submitting ? '로그인 중…' : '로그인'}
            </Button>
            <Link to="/signup" className={styles.switch}>
              처음 이용하시나요? <span className={styles.switchAction}>회원가입</span>
            </Link>
          </form>
        </div>
      </main>
    </div>
  )
}

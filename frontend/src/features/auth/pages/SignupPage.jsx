import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Checkbox, Input } from '../../../components/ui'
import { supabase } from '../../../lib/supabase'
import { toErrorMessage } from '../../../utils/errorMessages'
import AuthHero from '../components/AuthHero'
import { clearPendingProfile, savePendingProfile } from '../pendingProfile'
import styles from './AuthForm.module.css'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validate({ displayName, email, password, agreed }) {
  const errors = {}
  if (!displayName.trim()) errors.displayName = '공개 닉네임을 입력해 주세요.'
  else if (displayName.trim().length > 50) errors.displayName = '50자 이하로 입력해 주세요.'
  if (!EMAIL_PATTERN.test(email)) errors.email = '올바른 이메일 주소를 입력해 주세요.'
  if (password.length < 6) errors.password = '비밀번호는 6자 이상이어야 해요.'
  if (!agreed) errors.agreed = '약관에 동의해 주세요.'
  return errors
}

export default function SignupPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ displayName: '', email: '', password: '', agreed: false })
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const update = (key) => (value) => setForm((prev) => ({ ...prev, [key]: value }))
  const onInput = (key) => (e) => update(key)(e.target.value)

  async function handleSubmit(e) {
    e.preventDefault()
    const nextErrors = validate(form)
    setErrors(nextErrors)
    setFormError('')
    if (Object.keys(nextErrors).length > 0) return

    setSubmitting(true)
    const email = form.email.trim()
    // 프로필은 로그인 상태가 된 뒤 AuthProvider가 이 값으로 생성
    savePendingProfile({ email, displayName: form.displayName.trim() })

    const { data, error } = await supabase.auth.signUp({
      email,
      password: form.password,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    })
    setSubmitting(false)

    if (error) {
      clearPendingProfile()
      setFormError(toErrorMessage(error))
      return
    }
    // 이메일 인증이 켜져 있으면 이미 가입된 이메일도 오류 없이 빈 identities로 돌아옴
    if (data.user?.identities?.length === 0) {
      clearPendingProfile()
      setFormError(toErrorMessage({ code: 'user_already_exists' }))
      return
    }
    // 세션이 바로 생기면(이메일 인증 꺼짐) 가드가 홈으로 보내 줌
    if (!data.session) navigate('/signup/check-email', { state: { email } })
  }

  return (
    <div className={styles.page}>
      <main className={styles.body}>
        <AuthHero
          title="ART MATE 시작하기"
          description="미술 입시 학습 기록을 한곳에서 관리해 보세요."
        />

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <Input
            label="공개 닉네임"
            placeholder="서연의작업실"
            autoComplete="nickname"
            maxLength={50}
            value={form.displayName}
            onChange={onInput('displayName')}
            error={errors.displayName}
          />
          <p className={styles.hint}>커뮤니티 등에서 다른 사람에게 보이는 이름이에요.</p>
          <Input
            label="이메일"
            type="email"
            placeholder="student@example.com"
            autoComplete="email"
            value={form.email}
            onChange={onInput('email')}
            error={errors.email}
          />
          <Input
            label="비밀번호"
            type="password"
            placeholder="6자 이상 입력"
            autoComplete="new-password"
            value={form.password}
            onChange={onInput('password')}
            error={errors.password}
          />
          <Checkbox checked={form.agreed} onChange={update('agreed')}>
            서비스 이용약관과 개인정보 처리방침에 동의합니다.
          </Checkbox>
          {errors.agreed && <p className={styles.formError}>{errors.agreed}</p>}
          {formError && <p className={styles.formError}>{formError}</p>}

          <Button type="submit" disabled={submitting}>
            {submitting ? '가입하는 중…' : '회원가입'}
          </Button>
          <Link to="/login" className={styles.switch}>
            이미 계정이 있으신가요? 로그인
          </Link>
        </form>
      </main>
    </div>
  )
}

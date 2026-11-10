import { useState } from 'react'
import { Lock, Mail, Palette, User } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Badge, Button, Checkbox, Input, PageIntro } from '../../../components/ui'
import { supabase } from '../../../lib/supabase'
import { toErrorMessage } from '../../../utils/errorMessages'
import { clearPendingProfile, savePendingProfile } from '../pendingProfile'
import styles from './AuthForm.module.css'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validate({ displayName, email, password, agreed }) {
  const errors = {}
  if (!displayName.trim()) errors.displayName = '이름 또는 닉네임을 입력해 주세요.'
  else if (displayName.trim().length > 50) errors.displayName = '50자 이하로 입력해 주세요.'
  if (!EMAIL_PATTERN.test(email)) errors.email = '올바른 이메일 주소를 입력해 주세요.'
  if (password.length < 8) errors.password = '비밀번호는 8자 이상이어야 해요.'
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
      <TopBar title="회원가입" />
      <main className={styles.body}>
        <Badge className={styles.badge}>
          <Palette size={20} aria-hidden />
          학생 계정 만들기
        </Badge>
        <PageIntro title="성장 기록을 시작해 볼까요?" />

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <Input
            label="이름 또는 닉네임"
            icon={User}
            placeholder="김서연"
            autoComplete="nickname"
            value={form.displayName}
            onChange={onInput('displayName')}
            error={errors.displayName}
          />
          <Input
            label="이메일"
            icon={Mail}
            type="email"
            placeholder="name@example.com"
            autoComplete="email"
            value={form.email}
            onChange={onInput('email')}
            error={errors.email}
          />
          <Input
            label="비밀번호"
            icon={Lock}
            type="password"
            placeholder="8자 이상 입력"
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
            {submitting ? '가입하는 중…' : '회원가입 완료'}
          </Button>
        </form>

        <p className={styles.footer}>
          이미 계정이 있으신가요?
          <Link to="/login" className={styles.link}>
            로그인
          </Link>
        </p>
      </main>
    </div>
  )
}

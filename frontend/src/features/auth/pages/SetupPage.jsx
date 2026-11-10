import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import TopBar from '../../../components/layout/TopBar'
import { Button, Input, Select, Textarea } from '../../../components/ui'
import { useOptions } from '../../../hooks/useOptions'
import { toErrorMessage } from '../../../utils/errorMessages'
import { addTargetUniversity } from '../api'
import styles from './AuthForm.module.css'

/**
 * 학습 정보 설정 (v0.9 F-1): 학년 · 실기 유형 · 목표 대학 · 학습 목표
 * 실기 유형이 없는 학생은 탭 화면 대신 여기로 옴 (ProtectedRoute)
 */
export default function SetupPage() {
  const navigate = useNavigate()
  const { profile, updateProfile } = useAuth()
  const options = useOptions()
  const firstTime = !profile.practical_type
  const [grade, setGrade] = useState(profile.grade ?? '')
  const [practicalType, setPracticalType] = useState(profile.practical_type ?? '')
  const [university, setUniversity] = useState('')
  const [goal, setGoal] = useState(profile.learning_goal ?? '')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!grade || !practicalType) {
      setFormError('학년과 실기 유형을 선택해 주세요.')
      return
    }
    setSaving(true)
    setFormError('')
    try {
      // 목표 대학을 먼저 저장 (실패해도 다시 시도할 수 있도록, 프로필 저장 전에)
      if (university.trim()) await addTargetUniversity(university.trim())
      await updateProfile({
        grade,
        practical_type: practicalType,
        learning_goal: goal.trim() || null,
      })
      navigate('/home', { replace: true })
    } catch (err) {
      setFormError(toErrorMessage(err))
      setSaving(false)
    }
  }

  return (
    <div className={styles.page}>
      <TopBar title="학습 정보 설정" plain hideBack={firstTime} />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        <div className={styles.steps} aria-hidden>
          <span />
          <span />
          <span />
        </div>

        <div className={styles.setupIntro}>
          <h1 className={styles.setupTitle}>{'나에게 맞는 학습 공간을\n준비해 볼까요?'}</h1>
          <p className={styles.setupSub}>정보는 나중에 마이페이지에서 언제든 수정할 수 있습니다.</p>
        </div>

        <div className={styles.form}>
          <Select
            label="학년"
            placeholder="학년 선택"
            options={options?.grades}
            value={grade}
            onChange={(e) => setGrade(e.target.value)}
            required
          />
          <Select
            label="실기 유형"
            placeholder="실기 유형 선택"
            options={options?.practical_types}
            value={practicalType}
            onChange={(e) => setPracticalType(e.target.value)}
            required
          />
          <Input
            label="목표 대학·학과 (선택)"
            placeholder="예: 홍익대학교 시각디자인과"
            maxLength={100}
            value={university}
            onChange={(e) => setUniversity(e.target.value)}
          />
          <Textarea
            label="나의 학습 목표 (선택)"
            rows={4}
            maxLength={500}
            placeholder="예: 5시간 내 작품 마무리, 비례 보완"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          {formError && <p className={styles.formError}>{formError}</p>}
          <Button type="submit" disabled={saving}>
            {saving ? '저장하는 중…' : '설정 완료'}
          </Button>
        </div>
      </form>
    </div>
  )
}

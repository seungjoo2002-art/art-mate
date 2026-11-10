import { useCallback, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Input, Select, Textarea } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { toErrorMessage } from '../../../utils/errorMessages'
import { addTargetUniversity, deleteTargetUniversity, listTargetUniversities } from '../api'
import styles from './ProfileEditPage.module.css'

const MAX_TARGETS = 10 // 서버 제한

/** 마이페이지 → 프로필·학습 정보·목표 대학 수정 */
export default function ProfileEditPage() {
  const navigate = useNavigate()
  const { profile, updateProfile } = useAuth()
  const options = useOptions()
  const [displayName, setDisplayName] = useState(profile.display_name)
  const [grade, setGrade] = useState(profile.grade ?? '')
  const [practicalType, setPracticalType] = useState(profile.practical_type ?? '')
  const [goal, setGoal] = useState(profile.learning_goal ?? '')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  async function handleSave(e) {
    e.preventDefault()
    if (!displayName.trim()) {
      setFormError('공개 닉네임을 입력해 주세요.')
      return
    }
    setSaving(true)
    setFormError('')
    try {
      await updateProfile({
        display_name: displayName.trim(),
        grade: grade || null,
        practical_type: practicalType || null,
        learning_goal: goal.trim() || null,
      })
      navigate('/my', { replace: true })
    } catch (err) {
      setFormError(toErrorMessage(err))
      setSaving(false)
    }
  }

  return (
    <>
      <TopBar title="프로필·목표 대학 수정" belowHeader />
      <main className={styles.body}>
        <form className={styles.form} onSubmit={handleSave} noValidate>
          <h2 className={styles.heading}>프로필</h2>
          <Input
            label="공개 닉네임"
            maxLength={50}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <Select
            label="학년"
            placeholder="학년 선택"
            options={options?.grades}
            value={grade}
            onChange={(e) => setGrade(e.target.value)}
          />
          <Select
            label="주요 실기 유형"
            placeholder="실기 유형 선택"
            options={options?.practical_types}
            value={practicalType}
            onChange={(e) => setPracticalType(e.target.value)}
          />
          <Textarea
            label="학습 목표"
            rows={3}
            maxLength={500}
            placeholder="예: 5시간 내 작품 마무리, 비례 보완"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          {formError && <p className={styles.error}>{formError}</p>}
          <Button type="submit" disabled={saving}>
            {saving ? '저장하는 중…' : '프로필 저장'}
          </Button>
        </form>

        <TargetUniversities />
      </main>
    </>
  )
}

/** 목표 대학: 추가·삭제는 바로 저장됨 (1지망부터) */
function TargetUniversities() {
  const load = useCallback(() => listTargetUniversities(), [])
  const { data: targets, reload } = useAsync(load)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const full = (targets?.length ?? 0) >= MAX_TARGETS

  async function run(action) {
    setBusy(true)
    setError('')
    try {
      await action()
      reload()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function handleAdd(e) {
    e.preventDefault()
    if (!name.trim()) return
    run(async () => {
      await addTargetUniversity(name.trim())
      setName('')
    })
  }

  return (
    <section className={styles.form}>
      <h2 className={styles.heading}>목표 대학</h2>
      {targets?.length > 0 ? (
        <Card className={styles.list}>
          {targets.map((t) => (
            <div key={t.id} className={styles.row}>
              <span className={styles.priority}>{t.priority}지망</span>
              <span className={styles.university}>
                {t.university_name}
                {t.department && ` ${t.department}`}
              </span>
              <button
                type="button"
                className={styles.remove}
                onClick={() => run(() => deleteTargetUniversity(t.id))}
                disabled={busy}
                aria-label={`${t.university_name} 삭제`}
              >
                <Trash2 size={18} />
              </button>
            </div>
          ))}
        </Card>
      ) : (
        <p className={styles.caption}>아직 목표 대학이 없어요.</p>
      )}

      {!full && (
        <form className={styles.addRow} onSubmit={handleAdd}>
          <Input
            aria-label="목표 대학·학과"
            placeholder="예: 홍익대학교 시각디자인과"
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={styles.addInput}
          />
          <Button type="submit" size="md" fullWidth={false} disabled={busy || !name.trim()}>
            추가
          </Button>
        </form>
      )}
      {full && <p className={styles.caption}>목표 대학은 {MAX_TARGETS}곳까지 등록할 수 있어요.</p>}
      {error && <p className={styles.error}>{error}</p>}
    </section>
  )
}

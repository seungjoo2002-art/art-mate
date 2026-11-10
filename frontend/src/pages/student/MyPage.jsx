import { useCallback, useState } from 'react'
import { PencilLine } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { Button, Card, PageIntro } from '../../components/ui'
import { listTargetUniversities } from '../../features/auth/api'
import { getAiConsent, revokeAiConsent } from '../../features/feedback/aiApi'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './MyPage.module.css'

// 디자인 중 백엔드가 없는 항목(학업 성적·모의고사, 실기 유형 관리, 실기시험 목표 시간,
// 내 공개 작품 피드)은 API·화면이 생기면 추가
export default function MyPage() {
  const { profile, signOut } = useAuth()
  const options = useOptions()
  const loadTargets = useCallback(() => listTargetUniversities(), [])
  const { data: targets } = useAsync(loadTargets)

  const label = (list, code) => (code ? (options ? labelOf(options[list], code) : '') : null)
  const grade = label('grades', profile.grade)
  const practicalType = label('practical_types', profile.practical_type)
  const firstTarget = targets?.[0]

  return (
    <>
      <PageIntro title="마이페이지" description="학습 정보와 입시 목표를 관리합니다." />

      <Card className={styles.profile}>
        <span className={styles.avatar}>{profile.display_name.slice(0, 1)}</span>
        <div className={styles.profileText}>
          <p className={styles.name}>
            {profile.display_name}
            <span className={styles.role}>학생</span>
          </p>
          <p className={styles.sub}>{[profile.email, grade].filter(Boolean).join(' · ')}</p>
        </div>
        <Link to="/my/edit" className={styles.edit}>
          편집 <PencilLine size={16} aria-hidden />
        </Link>
      </Card>

      <section className={styles.section}>
        <h2 className={styles.heading}>나의 입시 정보</h2>
        <Card className={styles.list}>
          <InfoRow label="주요 실기 유형" value={practicalType} />
          <InfoRow
            label="목표 대학"
            value={
              firstTarget &&
              `${firstTarget.university_name}${targets.length > 1 ? ` 외 ${targets.length - 1}곳` : ''}`
            }
          />
          <InfoRow label="학습 목표" value={profile.learning_goal} />
        </Card>
        <Link to="/my/edit" className={styles.outline}>
          프로필·목표 대학 수정
        </Link>
      </section>

      <section className={styles.section}>
        <h2 className={styles.heading}>AI 기능 동의</h2>
        <Card className={styles.list}>
          <AiConsentRow purpose="FEEDBACK_SUMMARY" title="AI 피드백 정리" />
          <AiConsentRow purpose="GROWTH_COACHING" title="AI 성장 코칭" />
        </Card>
      </section>

      <Button variant="soft" className={styles.logout} onClick={signOut}>
        로그아웃
      </Button>
      <p className={styles.footnote}>지망 대학과 학습 목표는 커뮤니티에 공개하지 않습니다.</p>
    </>
  )
}

function InfoRow({ label, value }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowValue}>{value || '미설정'}</span>
    </div>
  )
}

/** AI 동의 상태 + 철회 (동의서에 "마이페이지에서 철회 가능"으로 안내함) */
function AiConsentRow({ purpose, title }) {
  const load = useCallback(() => getAiConsent(purpose), [purpose])
  const { data: consent, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleRevoke() {
    if (
      !window.confirm(
        `${title} 동의를 철회할까요? 진행 중인 AI 작업은 취소되고, 이미 만든 결과는 남아요.`,
      )
    ) {
      return
    }
    setBusy(true)
    setError('')
    try {
      await revokeAiConsent(purpose)
      reload()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{title}</span>
      {consent?.is_valid ? (
        <button type="button" className={styles.revoke} onClick={handleRevoke} disabled={busy}>
          {busy ? '철회하는 중…' : '동의함 · 철회'}
        </button>
      ) : (
        <span className={styles.rowValue}>{consent ? '동의 안 함' : ''}</span>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}

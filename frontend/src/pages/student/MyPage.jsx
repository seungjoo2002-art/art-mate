import { useCallback, useState } from 'react'
import { ChevronRight, PencilLine } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { Button, Card, PageIntro } from '../../components/ui'
import { listTargetUniversities } from '../../features/auth/api'
import { getAiConsent, revokeAiConsent } from '../../features/feedback/aiApi'
import { getConsent, revokeConsent } from '../../features/feedback/api'
import NotificationSettings from '../../features/notifications/components/NotificationSettings'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './MyPage.module.css'

// 디자인 중 백엔드가 없는 항목(학업 성적·모의고사, 실기 유형 관리, 실기시험 목표 시간,
// 시연 모드)은 API가 생기면 추가
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
          <p className={styles.sub}>
            {[profile.real_name, profile.email, grade].filter(Boolean).join(' · ')}
          </p>
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
        <h2 className={styles.heading}>기록 설정</h2>
        <SettingLink
          to="/archive?tab=feed"
          title="내 공개 작품 피드"
          description="커뮤니티에 공유한 작품 확인"
        />
      </section>

      <section className={styles.section}>
        <h2 className={styles.heading}>녹음·AI 기능 동의</h2>
        <Card className={styles.list}>
          <ConsentRow
            title="피드백 녹음"
            load={getConsent}
            revoke={revokeConsent}
            confirmMessage="녹음 동의를 철회할까요? 새로 녹음하거나 녹음 파일을 올릴 수 없고, 대기 중인 글자 변환은 취소돼요. 이미 저장한 녹음은 남아요."
          />
          <ConsentRow
            title="AI 피드백 정리"
            load={loadAiSummaryConsent}
            revoke={revokeAiSummaryConsent}
            confirmMessage={AI_REVOKE_MESSAGE}
          />
          <ConsentRow
            title="AI 성장 코칭"
            load={loadGrowthConsent}
            revoke={revokeGrowthConsent}
            confirmMessage={AI_REVOKE_MESSAGE}
          />
        </Card>
      </section>

      <section className={styles.section}>
        <h2 className={styles.heading}>설정</h2>
        <NotificationSettings />
        <Button variant="soft" className={styles.logout} onClick={signOut}>
          로그아웃
        </Button>
      </section>
      <p className={styles.footnote}>지망 대학과 학습 목표는 커뮤니티에 공개하지 않습니다.</p>
    </>
  )
}

/** 기록 설정의 이동 카드 (제목 + 설명 + >) */
function SettingLink({ to, title, description }) {
  return (
    <Card as={Link} to={to} className={styles.setting}>
      <span className={styles.settingText}>
        <span className={styles.settingTitle}>{title}</span>
        <span className={styles.settingDescription}>{description}</span>
      </span>
      <ChevronRight size={22} aria-hidden />
    </Card>
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

// 동의별 조회·철회 (모듈 상수라 렌더마다 새로 만들어지지 않음 → useAsync가 다시 부르지 않음)
const loadAiSummaryConsent = () => getAiConsent('FEEDBACK_SUMMARY')
const revokeAiSummaryConsent = () => revokeAiConsent('FEEDBACK_SUMMARY')
const loadGrowthConsent = () => getAiConsent('GROWTH_COACHING')
const revokeGrowthConsent = () => revokeAiConsent('GROWTH_COACHING')
const AI_REVOKE_MESSAGE =
  '동의를 철회할까요? 진행 중인 AI 작업은 취소되고, 이미 만든 결과는 남아요.'

/** 동의 상태 + 철회 (각 동의서에 "마이페이지에서 언제든 철회 가능"으로 안내함) */
function ConsentRow({ title, load, revoke, confirmMessage }) {
  const { data: consent, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleRevoke() {
    if (!window.confirm(`[${title}] ${confirmMessage}`)) return
    setBusy(true)
    setError('')
    try {
      await revoke()
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

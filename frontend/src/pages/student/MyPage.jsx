import { useCallback, useState } from 'react'
import {
  Bot,
  ChevronRight,
  GraduationCap,
  Images,
  LogOut,
  Mic,
  Palette,
  PencilLine,
  Sparkles,
  Target,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { PageIntro } from '../../components/ui'
import { listTargetUniversities } from '../../features/auth/api'
import DatasetConsentCard from '../../features/dataset/DatasetConsentCard'
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
      <PageIntro title="마이페이지" />

      {/* 프로필: 물감 테두리 동그라미 + 이름 + 편집 */}
      <div className={styles.profile}>
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
          <PencilLine size={14} aria-hidden /> 편집
        </Link>
      </div>

      <Group title="나의 입시 정보">
        <Row
          to="/my/edit"
          icon={Palette}
          tone="#f2933a"
          label="주요 실기 유형"
          value={practicalType}
        />
        <Row
          to="/my/edit"
          icon={GraduationCap}
          tone="#7c6ee6"
          label="목표 대학"
          value={
            !firstTarget
              ? null
              : `${firstTarget.university_name}${targets.length > 1 ? ` 외 ${targets.length - 1}곳` : ''}`
          }
        />
        <Row
          to="/my/edit"
          icon={Target}
          tone="#e0607e"
          label="학습 목표"
          value={profile.learning_goal}
        />
      </Group>
      <p className={styles.note}>지망 대학과 학습 목표는 커뮤니티에 공개하지 않습니다.</p>

      <Group title="기록">
        <Row to="/archive?tab=feed" icon={Images} tone="#3fa7d6" label="내 공개 작품 피드" />
      </Group>

      <Group title="녹음·AI 기능 동의">
        <ConsentRow
          icon={Mic}
          tone="#f2933a"
          title="피드백 녹음"
          load={getConsent}
          revoke={revokeConsent}
          confirmMessage="녹음 동의를 철회할까요? 새로 녹음하거나 녹음 파일을 올릴 수 없고, 대기 중인 글자 변환은 취소돼요. 이미 저장한 녹음은 남아요."
        />
        <ConsentRow
          icon={Bot}
          tone="#7c6ee6"
          title="AI 피드백 정리"
          load={loadAiSummaryConsent}
          revoke={revokeAiSummaryConsent}
          confirmMessage={AI_REVOKE_MESSAGE}
        />
        <ConsentRow
          icon={Sparkles}
          tone="#e0607e"
          title="AI 성장 코칭"
          load={loadGrowthConsent}
          revoke={revokeGrowthConsent}
          confirmMessage={AI_REVOKE_MESSAGE}
        />
      </Group>

      <section className={styles.group}>
        <h2 className={styles.groupTitle}>AI 첨삭 학습 데이터 (선택)</h2>
        <DatasetConsentCard />
      </section>

      <section className={styles.group}>
        <h2 className={styles.groupTitle}>알림</h2>
        <NotificationSettings />
      </section>

      <div className={styles.list}>
        <button type="button" className={`${styles.row} ${styles.logout}`} onClick={signOut}>
          <span className={styles.icon} style={{ '--tone': 'var(--color-danger)' }}>
            <LogOut size={16} aria-hidden />
          </span>
          <span className={styles.rowLabel}>로그아웃</span>
        </button>
      </div>
    </>
  )
}

/** 작은 회색 제목 + 흰 묶음 목록 (설정 앱처럼) */
function Group({ title, children }) {
  return (
    <section className={styles.group}>
      <h2 className={styles.groupTitle}>{title}</h2>
      <div className={styles.list}>{children}</div>
    </section>
  )
}

/** 목록 한 줄: 색 아이콘 · 이름 · 값 · › (to가 있으면 누르면 이동) */
function Row({ to, icon: Icon, tone, label, value }) {
  const body = (
    <>
      <span className={styles.icon} style={{ '--tone': tone }}>
        <Icon size={16} aria-hidden />
      </span>
      <span className={styles.rowLabel}>{label}</span>
      {value !== undefined && (
        <span className={`${styles.rowValue} ${value ? '' : styles.unset}`}>
          {value || '미설정'}
        </span>
      )}
      {to && <ChevronRight size={18} className={styles.chevron} aria-hidden />}
    </>
  )
  return to ? (
    <Link to={to} className={styles.row}>
      {body}
    </Link>
  ) : (
    <div className={styles.row}>{body}</div>
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
function ConsentRow({ icon: Icon, tone, title, load, revoke, confirmMessage }) {
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
    <div className={`${styles.row} ${styles.wrap}`}>
      <span className={styles.icon} style={{ '--tone': tone }}>
        <Icon size={16} aria-hidden />
      </span>
      <span className={styles.rowLabel}>{title}</span>
      {consent?.is_valid ? (
        <>
          <span className={`${styles.badge} ${styles.on}`}>동의함</span>
          <button type="button" className={styles.revoke} onClick={handleRevoke} disabled={busy}>
            {busy ? '철회하는 중…' : '철회'}
          </button>
        </>
      ) : (
        consent && <span className={styles.badge}>동의 안 함</span>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}

import { useState } from 'react'
import { Bot, LogOut, Mic, TrendingUp } from 'lucide-react'
import { useAuth } from '../../app/providers/AuthContext'
import TopBar from '../../components/layout/TopBar'
import DatasetConsentCard from '../../features/dataset/DatasetConsentCard'
import { getAiConsent, revokeAiConsent } from '../../features/feedback/aiApi'
import { getConsent, revokeConsent } from '../../features/feedback/api'
import NotificationSettings from '../../features/notifications/components/NotificationSettings'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import { Group, Row } from './MyRows'
import styles from './MyPage.module.css'

/** 마이페이지 > 설정: 녹음·AI 동의, 학습 데이터 동의, 알림, 로그아웃 */
export default function MySettingsPage() {
  const { signOut } = useAuth()
  return (
    <>
      <TopBar title="설정" belowHeader />
      <main className={styles.settings}>
        <Group title="녹음·AI 기능 동의">
          <ConsentRow
            icon={Mic}
            title="피드백 녹음"
            load={getConsent}
            revoke={revokeConsent}
            confirmMessage="녹음 동의를 철회할까요? 새로 녹음하거나 녹음 파일을 올릴 수 없고, 대기 중인 글자 변환은 취소돼요. 이미 저장한 녹음은 남아요."
          />
          <ConsentRow
            icon={Bot}
            title="AI 피드백 정리"
            load={loadAiSummaryConsent}
            revoke={revokeAiSummaryConsent}
            confirmMessage={AI_REVOKE_MESSAGE}
          />
          <ConsentRow
            icon={TrendingUp}
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

        <Group>
          <Row icon={LogOut} label="로그아웃" danger onClick={signOut} />
        </Group>
      </main>
    </>
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
function ConsentRow({ icon: Icon, title, load, revoke, confirmMessage }) {
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
      <span className={styles.icon}>
        <Icon size={17} aria-hidden />
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

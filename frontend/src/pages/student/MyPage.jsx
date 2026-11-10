import { useCallback, useState } from 'react'
import { LogOut } from 'lucide-react'
import { useAuth } from '../../app/providers/AuthContext'
import { Card, PageIntro } from '../../components/ui'
import { getAiConsent, revokeAiConsent } from '../../features/feedback/aiApi'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './MyPage.module.css'

export default function MyPage() {
  const { profile, signOut } = useAuth()

  return (
    <>
      <PageIntro
        eyebrow="MY ART MATE"
        title="나의 프로필"
        description="나만의 성장 목표와 설정을 관리해요."
      />

      <Card variant="dark" className={styles.profile}>
        <span className={styles.avatar}>{profile.display_name.slice(0, 1)}</span>
        <div>
          <p className={styles.name}>{profile.display_name}</p>
          <p className={styles.email}>{profile.email}</p>
        </div>
      </Card>

      <AiConsentRow purpose="FEEDBACK_SUMMARY" title="AI 피드백 정리 동의" />
      <AiConsentRow purpose="GROWTH_COACHING" title="AI 성장 코칭 동의" />

      <Card className={styles.menu}>
        <button type="button" className={styles.logout} onClick={signOut}>
          로그아웃
          <LogOut size={22} aria-hidden />
        </button>
      </Card>
    </>
  )
}

/** AI 동의 상태 + 철회 (동의서에 "마이 탭에서 철회 가능"으로 안내함) */
function AiConsentRow({ purpose, title }) {
  const load = useCallback(() => getAiConsent(purpose), [purpose])
  const { data: consent, reload } = useAsync(load)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleRevoke() {
    if (!window.confirm(`${title}를 철회할까요? 진행 중인 AI 작업은 취소되고, 이미 만든 결과는 남아요.`)) {
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

  if (!consent) return null

  return (
    <Card className={styles.menu}>
      <div className={styles.row}>
        <div>
          <p className={styles.rowTitle}>{title}</p>
          <p className={styles.rowSub}>{consent.is_valid ? '동의함' : '동의하지 않음'}</p>
        </div>
        {consent.is_valid && (
          <button type="button" className={styles.revoke} onClick={handleRevoke} disabled={busy}>
            {busy ? '철회하는 중…' : '동의 철회'}
          </button>
        )}
      </div>
      {error && <p className={styles.error}>{error}</p>}
    </Card>
  )
}

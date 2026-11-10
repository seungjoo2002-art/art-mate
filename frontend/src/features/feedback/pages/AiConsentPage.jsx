import { useCallback } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getAiConsent } from '../aiApi'
import AiConsentForm from '../components/AiConsentForm'
import styles from './FeedbackRecordPage.module.css'

/** AI 전송 동의. 동의하면 들어온 화면(state.from)으로 돌아감 */
export default function AiConsentPage() {
  const navigate = useNavigate()
  const from = useLocation().state?.from ?? '/archive'
  const load = useCallback(() => getAiConsent(), [])
  const { data: consent, error, reload } = useAsync(load)

  if (error) {
    return (
      <FullScreenStatus title="정보를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!consent) return <FullScreenStatus />
  if (consent.is_valid) return <Navigate to={from} replace />

  return (
    <>
      <TopBar title="AI 정리 동의" belowHeader />
      <main className={`${styles.body} ${styles.left}`}>
        <AiConsentForm
          requiredVersion={consent.required_version}
          onSaved={() => navigate(from, { replace: true, state: { aiConsented: true } })}
        />
      </main>
    </>
  )
}

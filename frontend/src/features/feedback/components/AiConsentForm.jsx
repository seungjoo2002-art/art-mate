import { useState } from 'react'
import { Button, Card, Checkbox, Select } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import { renewGuardianLink, saveAiConsent } from '../aiApi'
import { BLOCKED_REASONS, consentCopy, consentReasonMessage, guardianLink } from '../consentCopy'
import styles from './ConsentForm.module.css'

const THIS_YEAR = new Date().getFullYear()
const YEARS = Array.from({ length: 60 }, (_, i) => {
  const year = String(THIS_YEAR - 6 - i)
  return { code: year, label: `${year}년` }
})
const MONTHS = Array.from({ length: 12 }, (_, i) => {
  const month = String(i + 1).padStart(2, '0')
  return { code: month, label: `${i + 1}월` }
})

/** 보호자에게 보낼 확인 링크 (복사·공유). 토큰은 동의 응답에서 한 번만 받는다 */
function GuardianLinkPanel({ token, purpose }) {
  const [current, setCurrent] = useState(token)
  const [message, setMessage] = useState('')
  const link = current ? guardianLink(current) : null

  async function copy() {
    try {
      await navigator.clipboard.writeText(link)
      setMessage('링크를 복사했어요. 보호자에게 보내 주세요.')
    } catch {
      setMessage('복사하지 못했어요. 링크를 길게 눌러 복사해 주세요.')
    }
  }

  async function share() {
    try {
      await navigator.share({ title: 'ART MATE 보호자 동의', url: link })
    } catch {
      // 취소
    }
  }

  async function renew() {
    setMessage('')
    try {
      const status = await renewGuardianLink(purpose)
      setCurrent(status.guardian_token)
    } catch (error) {
      setMessage(toErrorMessage(error))
    }
  }

  return (
    <Card>
      <p className={styles.sub}>
        보호자(법정대리인)의 확인이 필요해요. 아래 링크를 보호자에게 보내 주세요.
        보호자가 링크에서 확인하면 AI 정리를 쓸 수 있어요. (링크는 7일 동안, 한 번만 쓸 수 있어요)
      </p>
      {link ? (
        <>
          <p className={styles.version} style={{ wordBreak: 'break-all' }}>
            {link}
          </p>
          <div className={styles.checks}>
            <Button onClick={copy}>링크 복사하기</Button>
            {typeof navigator !== 'undefined' && navigator.share && (
              <Button variant="soft" onClick={share}>
                보호자에게 공유하기
              </Button>
            )}
          </div>
        </>
      ) : (
        <Button variant="soft" onClick={renew}>
          보호자 확인 링크 다시 만들기
        </Button>
      )}
      {message && <p className={styles.sub}>{message}</p>}
    </Card>
  )
}

/**
 * AI 전송 동의 (녹음 동의와 별개, v0.9.6).
 * 생년월로 나이 구간만 확인 → 성인은 바로 유효, 만 18세 미만은 보호자 링크, 만 13세 미만은 이용 불가 안내.
 * status: GET /ai-processing-consents/me 응답 (provider·reason·required_version)
 */
export default function AiConsentForm({ purpose = 'FEEDBACK_SUMMARY', status, onSaved }) {
  const copy = consentCopy(purpose, status.provider)
  const [agreed, setAgreed] = useState(false)
  const [year, setYear] = useState('')
  const [month, setMonth] = useState('')
  const [result, setResult] = useState(null) // 저장 후 아직 유효하지 않은 동의 상태
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const pending = result ?? (status.reason === 'GUARDIAN_PENDING' ? status : null)
  const blockedReason = BLOCKED_REASONS.find((reason) => reason === (result ?? status).reason)
  const canSubmit = agreed && year && month && !submitting

  async function handleSubmit() {
    setSubmitting(true)
    setFormError('')
    try {
      const saved = await saveAiConsent({
        purpose,
        policyVersion: status.required_version,
        birthYearMonth: `${year}-${month}`,
      })
      if (saved.is_valid) {
        onSaved()
        return
      }
      setResult(saved)
    } catch (error) {
      setFormError(toErrorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  if (blockedReason) {
    return (
      <div className={styles.form}>
        <h2 className={styles.title}>{copy.title}</h2>
        <p className={styles.sub}>{consentReasonMessage(blockedReason)}</p>
      </div>
    )
  }

  if (pending) {
    return (
      <div className={styles.form}>
        <h2 className={styles.title}>보호자 확인이 필요해요</h2>
        <GuardianLinkPanel token={pending.guardian_token} purpose={purpose} />
      </div>
    )
  }

  return (
    <div className={styles.form}>
      <div>
        <h2 className={styles.title}>{copy.title}</h2>
        <p className={styles.sub}>{copy.sub}</p>
      </div>

      <Card>
        <dl className={styles.items}>
          {copy.items.map(([term, detail]) => (
            <div key={term} className={styles.item}>
              <dt>{term}</dt>
              <dd>{detail}</dd>
            </div>
          ))}
        </dl>
        <p className={styles.version}>동의서 버전 {status.required_version}</p>
      </Card>

      <div className={styles.checks}>
        <Select
          label="태어난 해"
          placeholder="연도"
          options={YEARS}
          value={year}
          onChange={(e) => setYear(e.target.value)}
        />
        <Select
          label="태어난 달"
          placeholder="월"
          options={MONTHS}
          value={month}
          onChange={(e) => setMonth(e.target.value)}
        />
        <Checkbox checked={agreed} onChange={setAgreed}>
          {copy.agree}
        </Checkbox>
      </div>

      {formError && <p className={styles.error}>{formError}</p>}
      <Button disabled={!canSubmit} onClick={handleSubmit}>
        {submitting ? '저장하는 중…' : copy.submit}
      </Button>
    </div>
  )
}

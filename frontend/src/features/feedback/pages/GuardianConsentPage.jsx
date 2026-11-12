import { useCallback, useState } from 'react'
import { useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Checkbox, Input, Select } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { confirmGuardianConsent, getGuardianConsent } from '../aiApi'
import { consentCopy } from '../consentCopy'
import styles from './FeedbackRecordPage.module.css'
import formStyles from '../components/ConsentForm.module.css'

const RELATIONSHIPS = [
  { code: 'PARENT', label: '부모' },
  { code: 'LEGAL_GUARDIAN', label: '그 밖의 법정대리인' },
]

/**
 * 보호자(법정대리인) AI 전송 동의 확인 (v0.9.6, 로그인 불필요). 학생이 보낸 링크로 연다.
 * 학생 이름·작품·전사 내용은 보여 주지 않고 동의 내용만 보여 준다. 링크는 한 번만 쓸 수 있다.
 */
export default function GuardianConsentPage() {
  const { token } = useParams()
  const load = useCallback(() => getGuardianConsent(token), [token])
  const { data, error } = useAsync(load)
  const [name, setName] = useState('')
  const [relationship, setRelationship] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [done, setDone] = useState(false)
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (error) {
    return (
      <FullScreenStatus
        title="확인할 수 없는 링크예요"
        description="이미 확인했거나 기간(7일)이 지난 링크예요. 학생에게 새 링크를 요청해 주세요."
      />
    )
  }
  if (!data) return <FullScreenStatus />
  if (done || data.status === 'CONFIRMED') {
    return (
      <FullScreenStatus
        title="동의를 확인했어요"
        description="이제 학생이 AI 첨삭 정리를 쓸 수 있어요. 동의는 학생 마이페이지에서 언제든 철회할 수 있어요."
      />
    )
  }

  const copy = consentCopy(data.purpose, data.provider)
  const canSubmit = name.trim() && relationship && agreed && !submitting

  async function handleSubmit() {
    setSubmitting(true)
    setFormError('')
    try {
      await confirmGuardianConsent(token, { guardianName: name.trim(), relationship })
      setDone(true)
    } catch (err) {
      setFormError(toErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <TopBar title="보호자 동의" hideBack />
      <main className={`${styles.body} ${styles.left}`}>
        <div className={formStyles.form}>
          <div>
            <h2 className={formStyles.title}>{copy.title} (보호자 확인)</h2>
            <p className={formStyles.sub}>
              자녀가 ART MATE에서 AI 첨삭 정리를 쓰려고 해요. 만 18세 미만은 보호자(법정대리인)의
              동의가 필요해요.
              {data.age_band === 'UNDER_13' &&
                ' 만 13세 미만은 동의하더라도 서비스 준비가 끝날 때까지 AI 정리를 쓸 수 없어요.'}
            </p>
          </div>
          <Card>
            <dl className={formStyles.items}>
              {copy.items.map(([term, detail]) => (
                <div key={term} className={formStyles.item}>
                  <dt>{term}</dt>
                  <dd>{detail}</dd>
                </div>
              ))}
            </dl>
            <p className={formStyles.version}>동의서 버전 {data.policy_version}</p>
          </Card>
          <div className={formStyles.checks}>
            <Input
              label="보호자 성명"
              value={name}
              maxLength={50}
              autoComplete="name"
              onChange={(e) => setName(e.target.value)}
            />
            <Select
              label="학생과의 관계"
              placeholder="선택"
              options={RELATIONSHIPS}
              value={relationship}
              onChange={(e) => setRelationship(e.target.value)}
            />
            <Checkbox checked={agreed} onChange={setAgreed}>
              {copy.guardianAgree}
            </Checkbox>
          </div>
          {formError && <p className={formStyles.error}>{formError}</p>}
          <Button disabled={!canSubmit} onClick={handleSubmit}>
            {submitting ? '저장하는 중…' : '동의하기'}
          </Button>
        </div>
      </main>
    </>
  )
}

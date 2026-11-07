import { useState } from 'react'
import { Button, Card, Checkbox } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import { saveConsent } from '../api'
import styles from './ConsentForm.module.css'

// 표시 항목: docs/frontend-integration-v0.5.md §2.6
const ITEMS = [
  ['수집 항목', '피드백 음성 녹음 파일, 녹음 길이·시각'],
  ['목적', '학생 본인의 첨삭 내용 복습, 담당 강사의 첨삭 확인(학원 연결 작품만)'],
  ['보관 기간', '학생이 녹음이나 작품을 삭제할 때까지'],
  ['공개 범위', '본인. 학원에 연결된 작품은 담당 강사·학원 관리자도 볼 수 있어요. 개인 작품 녹음은 본인만 볼 수 있어요.'],
  ['이후 안내', '음성을 텍스트로 바꾸는 기능(STT)은 별도로 안내한 뒤 적용돼요.'],
  ['동의 철회', '설정에서 언제든 철회할 수 있어요. 철회하면 새로 녹음할 수 없어요.'],
]

/** 녹음 전 필수 동의 화면. 체크박스는 기본 해제 */
export default function ConsentForm({ requiredVersion, onSaved }) {
  const [agreed, setAgreed] = useState(false)
  const [underFourteen, setUnderFourteen] = useState(false)
  const [guardianAgreed, setGuardianAgreed] = useState(false)
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const canSubmit = agreed && (!underFourteen || guardianAgreed) && !submitting

  async function handleSubmit() {
    setSubmitting(true)
    setFormError('')
    try {
      await saveConsent({
        policyVersion: requiredVersion,
        grantedBy: underFourteen ? 'GUARDIAN' : 'SELF',
      })
      onSaved()
    } catch (error) {
      setFormError(toErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.form}>
      <div>
        <h2 className={styles.title}>피드백 녹음 동의</h2>
        <p className={styles.sub}>녹음을 시작하기 전에 아래 내용을 확인해 주세요.</p>
      </div>

      <Card>
        <dl className={styles.items}>
          {ITEMS.map(([term, detail]) => (
            <div key={term} className={styles.item}>
              <dt>{term}</dt>
              <dd>{detail}</dd>
            </div>
          ))}
        </dl>
        <p className={styles.version}>동의서 버전 {requiredVersion}</p>
      </Card>

      <div className={styles.checks}>
        <Checkbox checked={agreed} onChange={setAgreed}>
          위 내용을 확인했고 피드백 음성 녹음에 동의합니다.
        </Checkbox>
        <Checkbox checked={underFourteen} onChange={setUnderFourteen}>
          만 14세 미만이에요.
        </Checkbox>
        {underFourteen && (
          <Checkbox checked={guardianAgreed} onChange={setGuardianAgreed}>
            보호자(법정대리인)에게 내용을 알리고 동의를 받았어요.
          </Checkbox>
        )}
      </div>

      {formError && <p className={styles.error}>{formError}</p>}
      <Button disabled={!canSubmit} onClick={handleSubmit}>
        {submitting ? '저장하는 중…' : '동의하고 녹음하기'}
      </Button>
    </div>
  )
}

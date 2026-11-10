import { useState } from 'react'
import { Button, Card, Checkbox } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import { saveAiConsent } from '../aiApi'
import styles from './ConsentForm.module.css'

// 표시 항목: docs/frontend-integration-v0.6.md §1 (법적 검토 전 초안 — 확정 문구 나오면 교체)
const ITEMS = [
  ['목적', '첨삭 녹음을 글로 바꾼 내용(전사문)을 요약·분류해 학습 기록으로 정리해요.'],
  ['제공받는 곳', 'Google LLC (Gemini API) · 미국 등 국외로 전송돼요.'],
  [
    '보내는 내용',
    '첨삭 녹음의 전사문(문장과 시각)만 보내요. 이름·학교·작품 제목·계정 정보는 보내지 않아요. 단, 녹음 안에서 말한 이름 등은 전사문에 포함될 수 있어요.',
  ],
  [
    '보관',
    'ART MATE: 전사문·요약은 녹음을 삭제할 때까지 보관해요. Google: 유료 API 약관에 따라 처리되며 모델 학습에 쓰이지 않아요.',
  ],
  ['거부할 권리', '동의하지 않아도 녹음과 재생은 그대로 쓸 수 있어요. AI 정리만 쓸 수 없어요.'],
  ['동의 철회', '마이 탭에서 언제든 철회할 수 있어요. 진행 중인 정리는 취소되고, 이미 만든 정리는 남아요.'],
]

/** AI 전송 동의 (녹음 동의와 별개). 체크박스는 기본 해제 */
export default function AiConsentForm({ requiredVersion, onSaved }) {
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
      await saveAiConsent({
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
        <h2 className={styles.title}>AI 피드백 정리 동의</h2>
        <p className={styles.sub}>AI로 첨삭을 정리하려면 아래 내용에 동의해 주세요.</p>
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
          위 내용을 확인했고 전사문을 AI(Google Gemini)로 보내는 데 동의합니다.
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
        {submitting ? '저장하는 중…' : '동의하고 AI로 정리하기'}
      </Button>
    </div>
  )
}

import { useState } from 'react'
import { Button, Card, Checkbox, Input } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import { getDatasetConsent, grantDatasetConsent, revokeDatasetConsent } from './api'
import styles from './DatasetConsentCard.module.css'

const thisMonth = () => new Date().toISOString().slice(0, 7)

/**
 * AI 첨삭 학습 활용 동의 (v0.9.8). AI 정리 동의와 별개이고 선택 사항이다.
 * 동의하면: 기준 사진이 확인된 선생님 피드백과 그 작품 사진을 가명 처리해 AI 첨삭 연구·학습에 쓸 수 있다.
 * 만 14세 미만은 보호자 동의 절차가 준비되기 전까지 동의할 수 없다.
 */
export default function DatasetConsentCard() {
  const { data: consent, reload } = useAsync(getDatasetConsent)
  const [birth, setBirth] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run(action) {
    setBusy(true)
    setError('')
    try {
      await action()
      reload()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const grant = () =>
    run(() =>
      grantDatasetConsent({ policyVersion: consent.required_version, birthYearMonth: birth }),
    )
  const revoke = () => {
    if (!window.confirm('학습 활용 동의를 철회할까요? 이후 학습 데이터에서 바로 빠져요.')) return
    run(revokeDatasetConsent)
  }

  if (!consent) return null

  return (
    <Card className={styles.card}>
      <p className={styles.text}>
        선생님 피드백과 그 피드백의 기준 작품 사진을 이름 없이(가명 처리) AI 미대입시 첨삭
        연구·학습에 쓰는 데 동의합니다. 선택 사항이며, 동의하지 않아도 모든 기능을 쓸 수 있어요.
        기준 사진이 확인되지 않은 피드백과 내 메모는 쓰지 않아요.
      </p>
      {consent.is_valid ? (
        <div className={styles.row}>
          <span className={styles.status}>
            동의함 · {new Date(consent.granted_at).toLocaleDateString('ko-KR')}
          </span>
          <button type="button" className={styles.revoke} onClick={revoke} disabled={busy}>
            {busy ? '철회하는 중…' : '철회'}
          </button>
        </div>
      ) : (
        <div className={styles.form}>
          <Input
            label="태어난 연월 (나이 확인용, 저장하지 않아요)"
            type="month"
            max={thisMonth()}
            value={birth}
            onChange={(e) => setBirth(e.target.value)}
          />
          <Checkbox checked={agreed} onChange={setAgreed}>
            위 내용에 동의합니다 (선택)
          </Checkbox>
          <Button onClick={grant} disabled={!agreed || !birth || busy}>
            {busy ? '저장하는 중…' : '학습 활용 동의하기'}
          </Button>
        </div>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </Card>
  )
}

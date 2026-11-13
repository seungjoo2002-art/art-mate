import { api } from '../../lib/api'

// v0.9.8 AI 첨삭 학습 활용 동의 (AI 정리 동의와 별개)
export const getDatasetConsent = () => api('/dataset-consents/me')

/** birthYearMonth: 'YYYY-MM' (연령 구간 계산에만 쓰고 저장하지 않음) */
export const grantDatasetConsent = ({ policyVersion, birthYearMonth }) =>
  api('/dataset-consents/me', {
    method: 'POST',
    body: { policy_version: policyVersion, agreed: true, birth_year_month: birthYearMonth },
  })

export const revokeDatasetConsent = () => api('/dataset-consents/me', { method: 'DELETE' })

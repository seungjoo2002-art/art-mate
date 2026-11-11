import { Cpu, PencilLine } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MODELS, PREFERENCES } from '../stt/models'
import styles from './BrowserSttStatus.module.css'

const PREFERENCE_LABELS = {
  auto: '자동 (권장)',
  tiny: MODELS.tiny.label,
  base: MODELS.base.label,
  small: `${MODELS.small.label} · 고성능 기기`,
  off: '사용 안 함 (서버에서 변환)',
}

function percent(progress) {
  if (!progress?.total) return null
  return Math.min(100, Math.round((progress.loaded / progress.total) * 100))
}

function message(state) {
  const plan = state.plan
  switch (state.phase) {
    case 'unsupported':
      return '이 기기에서는 바로 변환할 수 없어요. 저장하면 서버에서 변환해요 (수 분~수십 분).'
    case 'preparing': {
      const pct = percent(state.progress)
      return pct !== null && pct < 100
        ? `음성 인식 모델 준비 중 ${pct}% (처음 한 번 약 ${plan.downloadMb}MB, Wi-Fi 권장)`
        : '음성 인식 모델 불러오는 중…'
    }
    case 'transcribing':
      return '이 기기에서 녹음을 글로 바꾸는 중…'
    case 'done': {
      const seconds = (state.result.timings.totalMs / 1000).toFixed(1)
      return `글로 바꾸기 완료 (${seconds}초). 저장하면 결과를 확인·수정할 수 있어요.`
    }
    case 'failed':
      return '이 기기에서 변환하지 못했어요. 저장하면 서버에서 변환해요.'
    case 'skipped':
      return '저장하면 서버에서 변환해요 (수 분~수십 분).'
    default:
      return null
  }
}

/** 녹음 직후 기기 음성 인식 진행 상태 + 서버 처리·직접 입력 전환 */
export default function BrowserSttStatus({ state, onSkip, preference, onPreferenceChange, artworkId }) {
  const text = message(state)
  const busy = state.phase === 'preparing' || state.phase === 'transcribing'
  return (
    <div className={styles.box} role="status" aria-live="polite">
      {text && (
        <p className={styles.line}>
          {busy ? <span className={styles.spinner} aria-hidden /> : <Cpu size={16} aria-hidden />}
          <span>{text}</span>
        </p>
      )}
      <div className={styles.actions}>
        {busy && (
          <button type="button" className={styles.link} onClick={onSkip}>
            서버에서 처리하기
          </button>
        )}
        {artworkId && (
          <Link to={`/artworks/${artworkId}/notes/new`} className={styles.link}>
            <PencilLine size={14} aria-hidden /> 직접 글로 적기
          </Link>
        )}
        {onPreferenceChange && (
          <label className={styles.select}>
            <span>기기 음성 인식</span>
            <select value={preference} onChange={(e) => onPreferenceChange(e.target.value)}>
              {PREFERENCES.map((value) => (
                <option key={value} value={value}>
                  {PREFERENCE_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </div>
  )
}

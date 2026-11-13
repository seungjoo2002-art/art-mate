import { AlertCircle, CheckCircle2, Cloud, PencilLine } from 'lucide-react'
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

/** 실제 받은 바이트 기준 다운로드 비율 (모르면 null → 퍼센트를 표시하지 않음) */
function percent(progress) {
  if (!progress?.total) return null
  return Math.min(100, Math.round((progress.loaded / progress.total) * 100))
}

/**
 * state.phase
 *  녹음 화면(모델 미리 준비): idle | unsupported | preparing | ready | failed | skipped
 *  기기 전사 작업(deviceJobs): queued | preparing | transcribing | saving | done | server | failed
 * → { tone: busy | ok | info | warn, title, desc, pct }
 */
function message(state, { afterSave }) {
  const plan = state.plan
  switch (state.phase) {
    case 'unsupported':
      return {
        tone: 'info',
        title: '서버에서 글로 바꿔요',
        desc: '이 기기에서는 바로 변환할 수 없어요.',
      }
    case 'queued':
      return { tone: 'busy', title: '변환 대기 중', desc: '앞의 녹음 변환이 끝나면 이어서 바꿔요.' }
    case 'preparing': {
      const pct = percent(state.progress)
      return pct !== null && pct < 100
        ? {
            tone: 'busy',
            title: `음성 인식 모델 받는 중 ${pct}%`,
            desc: `처음 한 번만 약 ${plan.downloadMb}MB 받아요. Wi-Fi를 권장해요.`,
            pct,
          }
        : { tone: 'busy', title: '음성 인식 준비 중', desc: '잠시만 기다려 주세요.' }
    }
    case 'ready':
      return { tone: 'ok', title: '음성 인식 준비 완료', desc: '저장하면 바로 글로 바꿔요.' }
    case 'transcribing': {
      const chunk = state.chunk
      return {
        tone: 'busy',
        title: '음성을 글로 바꾸는 중',
        desc:
          chunk?.total > 1
            ? `${chunk.done}/${chunk.total} 구간 완료`
            : '화면을 닫지 말고 기다려 주세요.',
        pct: chunk?.total > 1 ? Math.round((chunk.done / chunk.total) * 100) : null,
      }
    }
    case 'saving':
      return { tone: 'busy', title: '변환한 글 저장 중', desc: '거의 다 됐어요.' }
    case 'done':
      return { tone: 'ok', title: '글로 바꾸기 완료', desc: null }
    case 'server':
      return { tone: 'info', title: '서버에서 변환 중', desc: '변환이 끝나면 여기에 보여 드려요.' }
    case 'failed':
      return afterSave
        ? {
            tone: 'warn',
            title: '이 기기에서 변환하지 못했어요',
            desc: '서버에서 처리하거나 직접 적어 주세요.',
          }
        : { tone: 'warn', title: '모델을 미리 준비하지 못했어요', desc: '저장할 때 다시 시도해요.' }
    case 'skipped':
      return { tone: 'info', title: '서버에서 글로 바꿔요', desc: '저장하면 서버로 보내 변환해요.' }
    default:
      return null
  }
}

const TONE_ICON = { ok: CheckCircle2, info: Cloud, warn: AlertCircle }

/** 기기 음성 인식 진행 상태 (녹음 화면·녹음 카드 공용) + 서버 처리·직접 입력 전환 */
export default function BrowserSttStatus({
  state,
  onSkip,
  preference,
  onPreferenceChange,
  artworkId,
  afterSave = false,
}) {
  const msg = message(state, { afterSave })
  const busy = msg?.tone === 'busy'
  const Icon = TONE_ICON[msg?.tone]
  const showSkip = busy && onSkip && state.phase !== 'saving'
  return (
    <div
      className={`${styles.box} ${msg ? styles[msg.tone] : ''}`}
      role="status"
      aria-live="polite"
    >
      {msg && (
        <div className={styles.head}>
          <span className={styles.icon} aria-hidden>
            {busy ? <span className={styles.spinner} /> : <Icon size={18} />}
          </span>
          <div className={styles.text}>
            <strong className={styles.title}>{msg.title}</strong>
            {msg.desc && <span className={styles.desc}>{msg.desc}</span>}
          </div>
        </div>
      )}
      {msg?.pct != null && (
        <div className={styles.bar} aria-hidden>
          <span style={{ width: `${msg.pct}%` }} />
        </div>
      )}
      {(showSkip || artworkId || onPreferenceChange) && (
        <div className={styles.actions}>
          {showSkip && (
            <button type="button" className={styles.action} onClick={onSkip}>
              서버에서 처리하기
            </button>
          )}
          {artworkId && (
            <Link to={`/artworks/${artworkId}/notes/new`} className={styles.action}>
              <PencilLine size={14} aria-hidden /> 직접 글로 적기
            </Link>
          )}
          {onPreferenceChange && (
            <label className={styles.select}>
              <span>음성 인식</span>
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
      )}
    </div>
  )
}

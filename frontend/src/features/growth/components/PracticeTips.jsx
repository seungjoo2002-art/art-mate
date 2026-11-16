import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Checkbox } from '../../../components/ui'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createTipTask, setRecommendationCompleted } from '../api'
import { TAG_LABELS, tipState } from '../growthView'
import styles from './PracticeTips.module.css'

/**
 * v1.0 최근 첨삭의 '다음 작품 연습 과제'(NEXT_TIP). AI 호출 없이 저장된 첨삭에서 꺼낸다.
 * "연습 과제로 담기" → 내 연습 과제(채택됨), 체크하면 완료 기록 (기존 맞춤 연습 과제와 같은 기록)
 * onChanged: 분석 다시 불러오기
 */
export default function PracticeTips({ tips = [], onChanged }) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')

  if (!tips.length) {
    return (
      <p className={styles.empty}>
        확정한 첨삭에 '다음 작품 연습 과제'가 생기면 여기에 모아 보여 드려요.
      </p>
    )
  }

  async function run(key, action) {
    setBusy(key)
    setError('')
    try {
      await action()
      onChanged?.()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className={styles.wrap}>
      <ul className={styles.list}>
        {tips.map((t) => {
          const state = tipState(t)
          const key = t.tip.item_id
          return (
            <li key={key} className={`${styles.item} ${state === 'done' ? styles.done : ''}`}>
              <div className={styles.head}>
                <span className={styles.tag}>{TAG_LABELS[t.tag] ?? t.tag}</span>
                {t.related_repeated && <span className={styles.repeated}>반복 실수 관련</span>}
              </div>
              <p className={styles.content}>{t.tip.content}</p>
              <Link to={`/feedbacks/${t.tip.feedback_id}`} className={styles.source}>
                {formatMonthDay(t.tip.work_date)} · {t.tip.artwork_title}
              </Link>
              {state === 'add' ? (
                <button
                  type="button"
                  className={styles.add}
                  disabled={busy !== null}
                  onClick={() => run(key, () => createTipTask(key))}
                >
                  {busy === key ? '담는 중…' : '연습 과제로 담기'}
                </button>
              ) : (
                <Checkbox
                  checked={state === 'done'}
                  disabled={busy !== null}
                  onChange={(checked) =>
                    run(key, () => setRecommendationCompleted(t.task.id, t.task.version, checked))
                  }
                >
                  {state === 'done' ? '연습 완료' : '연습했으면 체크'}
                </Checkbox>
              )}
            </li>
          )
        })}
      </ul>
      {error && <p className={styles.error}>{error}</p>}
      <p className={styles.note}>
        연습을 완료한 것과 실력이 향상된 것은 같은 뜻이 아니에요. 다음 작품 첨삭에서 다시 확인해 보세요.
      </p>
    </div>
  )
}

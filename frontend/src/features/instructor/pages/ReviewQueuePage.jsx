import { useCallback } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router-dom'
import { SegmentedTabs } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { listReviewQueue } from '../../academy/api'
import { FEEDBACK_STATUS, formatDateTime } from '../status'
import StatusBadge from '../StatusBadge'
import styles from '../Instructor.module.css'

const TABS = [
  { key: 'waiting', label: '검토 대기' },
  { key: 'approved', label: '승인됨' },
]

/** 담당 학생 첨삭 검토 목록 (대기: 오래된 순 — 먼저 받은 것부터 처리) */
export default function ReviewQueuePage() {
  const { academy } = useOutletContext()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'approved' ? 'approved' : 'waiting'
  const student = params.get('student') ?? undefined
  const base = `/instructor/academies/${academy.id}`

  const load = useCallback(
    () =>
      listReviewQueue(academy.id, {
        status: tab === 'approved' ? 'APPROVED' : undefined,
        studentMembershipId: student,
        limit: 100,
      }),
    [academy.id, tab, student],
  )
  const { data, error } = useAsync(load)

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <h1 className={styles.title}>첨삭 검토</h1>
          <p className={styles.subtitle}>
            학생이 기록한 강사 첨삭(녹음·글)을 AI가 정리한 초안이에요. 확인하고 승인해 주세요.
          </p>
        </div>
      </div>
      <SegmentedTabs
        label="검토 상태"
        tabs={TABS}
        value={tab}
        onChange={(key) => setParams(key === 'approved' ? { tab: key } : {})}
      />
      {student && (
        <p className={styles.hint}>
          한 학생만 보는 중 ·{' '}
          <Link to={`${base}/feedbacks${tab === 'approved' ? '?tab=approved' : ''}`} className={styles.link}>
            전체 보기
          </Link>
        </p>
      )}
      {error ? (
        <p className={styles.error}>{toErrorMessage(error)}</p>
      ) : !data ? (
        <p className={styles.hint}>불러오는 중…</p>
      ) : data.items.length === 0 ? (
        <p className={styles.empty}>
          {tab === 'approved' ? '승인한 첨삭이 없어요.' : '검토할 첨삭이 없어요.'}
        </p>
      ) : (
        <ul className={styles.list}>
          {data.items.map((f) => (
            <li key={f.id} className={styles.row}>
              <Link to={`${base}/feedbacks/${f.id}`} className={styles.rowLink}>
                <span className={styles.rowMain}>
                  <span className={styles.rowTitle}>
                    {f.student.display_name} · {f.artwork_title}
                  </span>
                  <span className={styles.rowSub}>
                    {f.recording_id ? `녹음 첨삭${f.recording_title ? ` · ${f.recording_title}` : ''}` : '글 첨삭'}{' '}
                    · {formatDateTime(tab === 'approved' ? f.updated_at : f.created_at)}
                  </span>
                  {f.summary && <span className={styles.rowSub}>{f.summary}</span>}
                </span>
                <StatusBadge status={FEEDBACK_STATUS[f.status]} fallback={f.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && data.total > data.items.length && (
        <p className={styles.hint}>
          전체 {data.total}건 중 {data.items.length}건을 보여 주고 있어요.
        </p>
      )}
    </>
  )
}

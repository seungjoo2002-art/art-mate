import { useCallback } from 'react'
import TopBar from '../../components/layout/TopBar'
import { Card } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import { listMyAcademies, listMyJoinRequests } from './api'
import JoinAcademyPanel from './JoinAcademyPanel'
import styles from './Academy.module.css'

const REQUEST = {
  PENDING: ['승인 대기', 'badgeWait'],
  APPROVED: ['승인됨', 'badgeOk'],
  REJECTED: ['거절됨', 'badgeNo'],
}

/** v1.0 학생: 내 학원 · 소속 신청. 학원 작품의 AI 첨삭 정리는 담당 강사가 확인·승인한다 */
export default function StudentAcademiesPage() {
  const load = useCallback(
    () =>
      Promise.all([listMyAcademies(), listMyJoinRequests()]).then(([academies, requests]) => ({
        academies: academies.items.filter((a) => a.status === 'ACTIVE'),
        requests: requests.items,
      })),
    [],
  )
  const { data, error, reload } = useAsync(load)
  const pending = data?.requests.filter((r) => r.status !== 'APPROVED') ?? []

  return (
    <>
      <TopBar title="내 학원" belowHeader plain />
      <main className={`${styles.panel} ${styles.page}`}>
        {error && <p className={styles.error}>{toErrorMessage(error)}</p>}
        {data && (
          <>
            <section className={styles.panel}>
              <h2 className={styles.heading}>소속 학원</h2>
              {data.academies.length === 0 ? (
                <p className={styles.empty}>아직 소속된 학원이 없어요.</p>
              ) : (
                <ul className={styles.statusList}>
                  {data.academies.map((a) => (
                    <li key={a.id} className={styles.statusItem}>
                      <strong>{a.name}</strong>
                      <span className={styles.badgeOk}>소속</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className={styles.sub}>
                새 작품을 만들 때 학원과 반을 고르면 담당 선생님이 작품을 보고, AI 첨삭 정리를 확인해
                줘요.
              </p>
            </section>
            {pending.length > 0 && (
              <section className={styles.panel}>
                <h2 className={styles.heading}>소속 신청</h2>
                <ul className={styles.statusList}>
                  {pending.map((r) => (
                    <li key={r.id} className={styles.statusItem}>
                      <div className={styles.resultMain}>
                        <strong>{r.academy_name}</strong>
                        {r.review_note && <span className={styles.sub}>{r.review_note}</span>}
                      </div>
                      <span className={styles[REQUEST[r.status][1]]}>{REQUEST[r.status][0]}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <Card>
              <section className={styles.panel}>
                <h2 className={styles.heading}>학원 찾기</h2>
                <JoinAcademyPanel
                  excludeIds={[
                    ...data.academies.map((a) => a.id),
                    ...data.requests.filter((r) => r.status === 'PENDING').map((r) => r.academy_id),
                  ]}
                  onRequested={reload}
                />
              </section>
            </Card>
          </>
        )}
      </main>
    </>
  )
}

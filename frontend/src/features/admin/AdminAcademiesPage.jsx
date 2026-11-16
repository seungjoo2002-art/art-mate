import { useCallback, useEffect, useState } from 'react'
import { LogOut } from 'lucide-react'
import { useAuth } from '../../app/providers/AuthContext'
import { ACADEMY_STATUS_LABELS } from '../../app/roles'
import { SegmentedTabs } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import { listAcademiesForReview, reviewAcademy } from '../academy/api'
import { formatDateTime } from '../instructor/status'
import styles from '../instructor/Instructor.module.css'

const TABS = [
  { key: 'PENDING_APPROVAL', label: '승인 대기' },
  { key: 'ACTIVE', label: '운영 중' },
  { key: 'REJECTED', label: '반려' },
]

/** v1.0 시스템 관리자(ADMIN): 학원 등록 신청 승인·반려. ADMIN은 API로 부여하지 않는다 (DB에서 지정) */
export default function AdminAcademiesPage() {
  const { profile, signOut } = useAuth()
  const [status, setStatus] = useState('PENDING_APPROVAL')
  const load = useCallback(() => listAcademiesForReview(status), [status])
  const { data, error, reload } = useAsync(load)
  const [busy, setBusy] = useState(null)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    const root = document.documentElement
    root.dataset.layout = 'wide'
    return () => {
      delete root.dataset.layout
    }
  }, [])

  async function decide(academy, decision) {
    let note = null
    if (decision === 'REJECT') {
      note = window.prompt(`${academy.name} 등록을 반려하는 이유 (신청자에게 보여요)`)
      if (note === null) return
    }
    setBusy(academy.id)
    setActionError('')
    try {
      await reviewAcademy(academy.id, decision, note)
      reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.brand}>
          <span className={styles.mark}>A</span>
          <span className={styles.brandText}>ART MATE</span>
          <span className={styles.brandRole}>운영</span>
        </span>
        <div className={styles.headerRight}>
          <span className={styles.userName}>{profile.display_name}</span>
          <button type="button" className={styles.iconButton} onClick={signOut} aria-label="로그아웃">
            <LogOut size={20} />
          </button>
        </div>
      </header>
      <main className={styles.main}>
        <div className={styles.pageHead}>
          <div>
            <h1 className={styles.title}>학원 등록 심사</h1>
            <p className={styles.subtitle}>
              승인하면 신청한 강사가 원장이 되고, 학생·강사가 소속을 신청할 수 있어요.
            </p>
          </div>
        </div>
        <SegmentedTabs label="학원 상태" tabs={TABS} value={status} onChange={setStatus} />
        {actionError && <p className={styles.error}>{actionError}</p>}
        {error ? (
          <p className={styles.error}>{toErrorMessage(error)}</p>
        ) : !data ? (
          <p className={styles.hint}>불러오는 중…</p>
        ) : data.items.length === 0 ? (
          <p className={styles.empty}>{ACADEMY_STATUS_LABELS[status]} 학원이 없어요.</p>
        ) : (
          <ul className={styles.list}>
            {data.items.map((a) => (
              <li key={a.id} className={styles.row}>
                <span className={styles.rowMain}>
                  <span className={styles.rowTitle}>{a.name}</span>
                  <span className={styles.rowSub}>
                    신청 {formatDateTime(a.created_at)}
                    {a.description ? ` · ${a.description}` : ''}
                    {a.review_note ? ` · 메모: ${a.review_note}` : ''}
                  </span>
                </span>
                {status === 'PENDING_APPROVAL' && (
                  <div className={styles.rowActions}>
                    <button
                      type="button"
                      className={styles.smallPrimary}
                      disabled={busy !== null}
                      onClick={() => decide(a, 'APPROVE')}
                    >
                      승인
                    </button>
                    <button
                      type="button"
                      className={styles.smallButton}
                      disabled={busy !== null}
                      onClick={() => decide(a, 'REJECT')}
                    >
                      반려
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  )
}

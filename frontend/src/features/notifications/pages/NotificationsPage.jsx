import { useCallback, useState } from 'react'
import { X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  deleteNotification,
  listNotifications,
  markAllRead,
  markRead,
  notificationLink,
} from '../api'
import styles from './NotificationsPage.module.css'

/** 알림 목록: 누르면 읽음 처리 후 관련 화면으로, 모두 읽음, 삭제 */
export default function NotificationsPage() {
  const navigate = useNavigate()
  const load = useCallback(() => listNotifications(), [])
  const { data, error, reload } = useAsync(load)
  const [actionError, setActionError] = useState('')

  async function run(action) {
    setActionError('')
    try {
      await action()
      reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
    }
  }

  async function open(n) {
    if (!n.is_read) await markRead(n.id).catch(() => {})
    const link = notificationLink(n)
    if (link) navigate(link)
    else reload()
  }

  return (
    <>
      <TopBar
        title="알림"
        belowHeader
        plain
        right={
          data?.unread_count > 0 && (
            <button type="button" className={styles.readAll} onClick={() => run(markAllRead)}>
              모두 읽음
            </button>
          )
        }
      />
      <main className={styles.body}>
        {error && <Card variant="soft">{toErrorMessage(error)}</Card>}
        {actionError && <p className={styles.error}>{actionError}</p>}
        {data && data.items.length === 0 && (
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>새 알림이 없어요.</p>
            <p className={styles.emptySub}>성장 리포트, 연습 과제, 학습 목표 안내가 여기에 와요.</p>
          </div>
        )}
        <ul className={styles.list}>
          {data?.items.map((n) => (
            <li key={n.id} className={`${styles.item} ${n.is_read ? '' : styles.unread}`}>
              <button type="button" className={styles.content} onClick={() => open(n)}>
                {!n.is_read && <span className={styles.dot} aria-label="안 읽음" />}
                <span className={styles.title}>{n.title}</span>
                {n.body && <span className={styles.text}>{n.body}</span>}
                <span className={styles.time}>{formatUploadedAt(n.created_at)}</span>
              </button>
              <button
                type="button"
                className={styles.remove}
                onClick={() => run(() => deleteNotification(n.id))}
                aria-label="알림 삭제"
              >
                <X size={18} />
              </button>
            </li>
          ))}
        </ul>
      </main>
    </>
  )
}

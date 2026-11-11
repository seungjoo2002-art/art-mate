import { useCallback, useState } from 'react'
import { Card, Select, Toggle } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getPreferences, updatePreferences } from '../api'
import styles from './NotificationSettings.module.css'

const ITEMS = [
  { key: 'report_ready', label: '성장 리포트 완성' },
  { key: 'task_recommended', label: '새 맞춤 연습 과제' },
  { key: 'task_reminder', label: '미완료 연습 과제 안내' },
  { key: 'goal_check', label: '학습 목표 점검 (월 1회)' },
]
const DAYS = [1, 3, 5, 7, 14].map((d) => ({ code: String(d), label: `${d}일 후` }))

/** 알림 설정 (v0.9 F-9). 바꾸는 즉시 저장 */
export default function NotificationSettings() {
  const load = useCallback(() => getPreferences(), [])
  const { data } = useAsync(load)
  const [prefs, setPrefs] = useState(null) // 저장 응답 (없으면 처음 받은 값)
  const [error, setError] = useState('')
  const current = prefs ?? data

  async function save(patch) {
    setError('')
    const previous = current
    setPrefs({ ...current, ...patch }) // 먼저 화면에 반영
    try {
      setPrefs(await updatePreferences(patch))
    } catch (err) {
      setPrefs(previous)
      setError(toErrorMessage(err))
    }
  }

  if (!current) return null

  return (
    <Card className={styles.card}>
      <p className={styles.title}>알림 설정</p>
      {ITEMS.map((item) => (
        <div key={item.key} className={styles.row}>
          <span>{item.label}</span>
          <Toggle
            checked={current[item.key]}
            onChange={(checked) => save({ [item.key]: checked })}
            label={item.label}
          />
        </div>
      ))}
      {current.task_reminder && (
        <div className={styles.row}>
          <span>미완료 안내 시점</span>
          <Select
            aria-label="미완료 안내 시점"
            options={
              DAYS.some((d) => d.code === String(current.reminder_after_days))
                ? DAYS
                : [
                    ...DAYS,
                    {
                      code: String(current.reminder_after_days),
                      label: `${current.reminder_after_days}일 후`,
                    },
                  ]
            }
            value={String(current.reminder_after_days)}
            onChange={(e) => save({ reminder_after_days: Number(e.target.value) })}
            className={styles.select}
          />
        </div>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </Card>
  )
}

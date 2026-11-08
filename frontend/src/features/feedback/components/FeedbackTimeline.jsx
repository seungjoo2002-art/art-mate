import { useCallback, useState } from 'react'
import { Mic, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { deleteRecording, listRecordings } from '../api'
import { formatDuration } from '../format'
import RecordingPlayer from './RecordingPlayer'
import styles from './FeedbackTimeline.module.css'

/** 시각이 있는 항목은 오래된 순, 시각 없는 항목(빈 단계)은 원래 순서대로 맨 뒤 */
function sortByTime(items) {
  // 문자열 비교는 시간대 표기(Z, +09:00)가 섞이면 틀리므로 시각으로 비교
  const timed = items
    .filter((item) => item.time)
    .sort((a, b) => Date.parse(a.time) - Date.parse(b.time))
  return [...timed, ...items.filter((item) => !item.time)]
}

/**
 * 작품 상세의 타임라인: 단계 사진 카드(items: { key, time, node })와 피드백 녹음을 시간순으로 섞어 보여 줌
 * 아래에 피드백 녹음 버튼
 */
export default function FeedbackTimeline({ artworkId, items }) {
  const load = useCallback(() => listRecordings(artworkId), [artworkId])
  const { data, reload } = useAsync(load)
  const [deletingId, setDeletingId] = useState(null)
  const [deleteError, setDeleteError] = useState('')

  async function handleDelete(recording) {
    if (!window.confirm('이 녹음을 삭제할까요? 삭제하면 되돌릴 수 없어요.')) return
    setDeletingId(recording.id)
    setDeleteError('')
    try {
      await deleteRecording(artworkId, recording.id)
      reload()
    } catch (error) {
      setDeleteError(toErrorMessage(error))
    } finally {
      setDeletingId(null)
    }
  }

  // 이 API는 페이지 객체가 아니라 배열을 그대로 돌려줌
  const recordingItems = (data ?? []).map((recording) => ({
    key: recording.id,
    time: recording.recorded_at ?? recording.uploaded_at ?? recording.created_at,
    node: (
      <div className={styles.recording}>
        <div className={styles.header}>
          <span className={styles.icon}>
            <Mic size={20} aria-hidden />
          </span>
          <div className={styles.meta}>
            <span className={styles.title}>{recording.title ?? '피드백 녹음'}</span>
            <span className={styles.sub}>{formatDuration(recording.duration_ms)}</span>
          </div>
          <button
            type="button"
            className={styles.delete}
            onClick={() => handleDelete(recording)}
            disabled={deletingId === recording.id}
            aria-label="녹음 삭제"
          >
            <Trash2 size={20} />
          </button>
        </div>
        <RecordingPlayer artworkId={artworkId} recording={recording} />
      </div>
    ),
  }))

  return (
    <section className={styles.section}>
      <ol className={styles.timeline}>
        {sortByTime([...items, ...recordingItems]).map((item) => (
          <li key={item.key} className={styles.entry}>
            {item.time && <span className={styles.time}>{formatUploadedAt(item.time)}</span>}
            {item.node}
          </li>
        ))}
      </ol>
      {deleteError && <p className={styles.error}>{deleteError}</p>}

      <Link to={`/artworks/${artworkId}/recordings/new`} className={styles.recordButton}>
        <Mic size={22} aria-hidden />
        피드백 녹음
      </Link>
    </section>
  )
}

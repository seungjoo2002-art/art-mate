import { useCallback, useState } from 'react'
import { Mic, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { deleteRecording, listRecordings } from '../api'
import { formatDuration } from '../format'
import RecordingPlayer from './RecordingPlayer'
import styles from './RecordingList.module.css'

/** 작품 상세 화면 하단: 피드백 녹음 버튼 + 녹음 목록 */
export default function RecordingList({ artworkId }) {
  const load = useCallback(() => listRecordings(artworkId), [artworkId])
  const { data, reload } = useAsync(load)
  const recordings = data ?? [] // 이 API는 페이지 객체가 아니라 배열을 그대로 돌려줌
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

  return (
    <section className={styles.section}>
      <Link to={`/artworks/${artworkId}/recordings/new`} className={styles.recordButton}>
        <Mic size={22} aria-hidden />
        피드백 녹음
      </Link>

      {recordings.length > 0 && (
        <>
          <h2 className={styles.heading}>피드백 녹음 {recordings.length}</h2>
          <ul className={styles.list}>
            {recordings.map((recording) => (
              <li key={recording.id} className={styles.item}>
                <div className={styles.header}>
                  <div className={styles.meta}>
                    <span className={styles.title}>{recording.title ?? '피드백 녹음'}</span>
                    <span className={styles.sub}>
                      {formatUploadedAt(recording.recorded_at ?? recording.created_at)} ·{' '}
                      {formatDuration(recording.duration_ms)}
                    </span>
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
              </li>
            ))}
          </ul>
          {deleteError && <p className={styles.error}>{deleteError}</p>}
        </>
      )}
    </section>
  )
}

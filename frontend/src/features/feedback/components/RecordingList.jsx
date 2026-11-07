import { useCallback } from 'react'
import { Mic } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { formatUploadedAt } from '../../../utils/date'
import { listRecordings } from '../api'
import { formatDuration } from '../format'
import RecordingPlayer from './RecordingPlayer'
import styles from './RecordingList.module.css'

/** 작품 상세 화면 하단: 피드백 녹음 버튼 + 녹음 목록 */
export default function RecordingList({ artworkId }) {
  const load = useCallback(() => listRecordings(artworkId), [artworkId])
  const { data } = useAsync(load)
  const recordings = data?.items ?? []

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
                <div className={styles.meta}>
                  <span className={styles.title}>{recording.title ?? '피드백 녹음'}</span>
                  <span className={styles.sub}>
                    {formatUploadedAt(recording.recorded_at ?? recording.created_at)} ·{' '}
                    {formatDuration(recording.duration_ms)}
                  </span>
                </div>
                <RecordingPlayer artworkId={artworkId} recording={recording} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

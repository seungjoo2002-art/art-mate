import { useCallback, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  getStaffArtwork,
  getStaffRecordingUrl,
  getStaffSummary,
  getStaffTranscript,
  listReviewQueue,
  listStaffRecordings,
  requestStaffSummary,
  requestStaffTranscription,
} from '../../academy/api'
import { stagePhotos, stagesWithPhotos } from '../../artworks/stages'
import { FEEDBACK_STATUS, TRANSCRIPTION_STATUS, formatClock, formatDateTime } from '../status'
import StatusBadge from '../StatusBadge'
import styles from '../Instructor.module.css'

/** 담당 학생 작품 상세: 단계별 사진, 녹음(재생·전사·AI 정리), 이 작품의 첨삭 */
export default function StaffArtworkPage() {
  const { academy } = useOutletContext()
  const { artworkId } = useParams()
  const base = `/instructor/academies/${academy.id}`

  const load = useCallback(async () => {
    const artwork = await getStaffArtwork(academy.id, artworkId)
    const [recordings, waiting, approved] = await Promise.all([
      listStaffRecordings(academy.id, artworkId),
      listReviewQueue(academy.id, { studentMembershipId: artwork.student.membership_id, limit: 100 }),
      listReviewQueue(academy.id, {
        status: 'APPROVED',
        studentMembershipId: artwork.student.membership_id,
        limit: 100,
      }),
    ])
    const feedbacks = [...waiting.items, ...approved.items].filter((f) => f.artwork_id === artworkId)
    return { artwork, recordings, feedbacks }
  }, [academy.id, artworkId])
  const { data, error, reload } = useAsync(load)

  if (error) {
    return (
      <div className={styles.empty}>
        <p>{toErrorMessage(error)}</p>
        <Link to={`${base}/artworks`} className={styles.link}>
          작품 목록으로
        </Link>
      </div>
    )
  }
  if (!data) return <p className={styles.hint}>불러오는 중…</p>

  const { artwork, recordings, feedbacks } = data
  const stages = stagesWithPhotos(artwork)

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <Link to={`${base}/artworks`} className={styles.link}>
            &lt; 학생 작품
          </Link>
          <h1 className={styles.title}>{artwork.title}</h1>
          <p className={styles.subtitle}>
            {artwork.student.display_name} · {formatMonthDay(artwork.work_date)}
            {artwork.topic ? ` · ${artwork.topic}` : ''}
            {artwork.actual_minutes ? ` · ${artwork.actual_minutes}분` : ''}
          </p>
        </div>
        <span className={artwork.work_status === 'COMPLETED' ? styles.statusDone : styles.status}>
          {artwork.work_status === 'COMPLETED' ? '완성' : '작업 중'}
        </span>
      </div>

      <div className={styles.twoCol}>
        <section className={styles.section} aria-label="단계별 사진">
          {stages.map((stage) => {
            const photos = stage.id ? stagePhotos(artwork, stage.id) : stage.photo ? [stage.photo] : []
            return (
              <div key={stage.key} className={styles.section}>
                <h2 className={styles.sectionTitle}>
                  {stage.label} <span className={styles.hint}>{photos.length}장</span>
                </h2>
                {photos.length === 0 ? (
                  <p className={styles.empty}>아직 올린 사진이 없어요.</p>
                ) : (
                  <div className={styles.photos}>
                    {photos.map((photo) => (
                      <a
                        key={photo.id}
                        href={photo.url ?? undefined}
                        target="_blank"
                        rel="noreferrer"
                        className={styles.photo}
                      >
                        {photo.url ? (
                          <img src={photo.url} alt={`${stage.label} 사진`} loading="lazy" />
                        ) : null}
                        {photo.is_representative && <span className={styles.photoLabel}>대표</span>}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </section>

        <div className={styles.section}>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>이 작품의 첨삭</h2>
            {feedbacks.length === 0 ? (
              <p className={styles.empty}>아직 AI가 정리한 첨삭이 없어요.</p>
            ) : (
              <ul className={styles.list}>
                {feedbacks.map((f) => (
                  <li key={f.id} className={styles.row}>
                    <Link to={`${base}/feedbacks/${f.id}`} className={styles.rowLink}>
                      <span className={styles.rowMain}>
                        <span className={styles.rowTitle}>
                          {f.recording_id ? '녹음 첨삭' : '글 첨삭'} · {formatDateTime(f.created_at)}
                        </span>
                        {f.summary && <span className={styles.rowSub}>{f.summary}</span>}
                      </span>
                      <StatusBadge status={FEEDBACK_STATUS[f.status]} fallback={f.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>녹음</h2>
            {recordings.length === 0 ? (
              <p className={styles.empty}>
                녹음이 없어요. 학생이 수업 중 강사 첨삭을 녹음하면 여기에 보여요.
              </p>
            ) : (
              <ul className={styles.list}>
                {recordings.map((rec) => (
                  <RecordingRow
                    key={rec.id}
                    academyId={academy.id}
                    artworkId={artwork.id}
                    recording={rec}
                    base={base}
                    onChanged={reload}
                  />
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  )
}

function RecordingRow({ academyId, artworkId, recording, base, onChanged }) {
  const [audioUrl, setAudioUrl] = useState(null)
  const [transcript, setTranscript] = useState(null)
  const [summary, setSummary] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')
  const status = TRANSCRIPTION_STATUS[recording.transcription_status]
  const transcribed = recording.transcription_status === 'COMPLETED'

  async function run(key, action) {
    setBusy(key)
    setError('')
    try {
      await action()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <li className={styles.row}>
      <span className={styles.rowMain}>
        <span className={styles.rowTitle}>
          {recording.title || '첨삭 녹음'} · {formatClock(recording.duration_ms)}
        </span>
        <span className={styles.rowSub}>{formatDateTime(recording.recorded_at ?? recording.created_at)}</span>
      </span>
      <StatusBadge status={status} fallback={recording.transcription_status} />
      <div className={styles.rowActions}>
        {recording.audio_available && !audioUrl && (
          <button
            type="button"
            className={styles.smallButton}
            disabled={busy !== null}
            onClick={() =>
              run('audio', async () =>
                setAudioUrl((await getStaffRecordingUrl(academyId, artworkId, recording.id)).url),
              )
            }
          >
            재생
          </button>
        )}
        {transcribed ? (
          <>
            <button
              type="button"
              className={styles.smallButton}
              disabled={busy !== null}
              onClick={() =>
                transcript
                  ? setTranscript(null)
                  : run('transcript', async () =>
                      setTranscript(await getStaffTranscript(academyId, artworkId, recording.id)),
                    )
              }
            >
              {transcript ? '전사 닫기' : '전사 보기'}
            </button>
            <button
              type="button"
              className={styles.smallButton}
              disabled={busy !== null}
              onClick={() =>
                run('summary', async () => {
                  const current = await getStaffSummary(academyId, artworkId, recording.id)
                  setSummary(current)
                })
              }
            >
              AI 정리 상태
            </button>
          </>
        ) : (
          (recording.transcription_status === 'NOT_REQUESTED' ||
            recording.transcription_status === 'FAILED') && (
            <button
              type="button"
              className={styles.smallPrimary}
              disabled={busy !== null || !recording.audio_available}
              onClick={() =>
                run('stt', async () => {
                  await requestStaffTranscription(academyId, artworkId, recording.id)
                  onChanged()
                })
              }
            >
              전사 요청
            </button>
          )
        )}
      </div>
      {audioUrl && (
        <audio controls src={audioUrl} className={styles.fullRow} autoPlay />
      )}
      {summary && (
        <p className={styles.hint}>
          {summary.feedback_id ? (
            <Link to={`${base}/feedbacks/${summary.feedback_id}`} className={styles.link}>
              AI 정리 보기 ({FEEDBACK_STATUS[summary.feedback_status]?.label ?? summary.feedback_status})
            </Link>
          ) : summary.job && ['QUEUED', 'RUNNING'].includes(summary.job.status) ? (
            'AI가 정리하는 중이에요.'
          ) : (
            <button
              type="button"
              className={styles.smallPrimary}
              disabled={busy !== null}
              onClick={() =>
                run('summarize', async () => {
                  await requestStaffSummary(academyId, artworkId, recording.id)
                  setSummary(await getStaffSummary(academyId, artworkId, recording.id))
                })
              }
            >
              AI 정리 요청
            </button>
          )}
        </p>
      )}
      {transcript && (
        <ol className={`${styles.transcript} ${styles.fullRow}`}>
          {transcript.segments.map((seg) => (
            <li key={seg.index}>
              <span className={styles.time}>{formatClock(seg.start_ms)}</span>
              {seg.text}
            </li>
          ))}
        </ol>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </li>
  )
}

import { useState } from 'react'
import { Mic, Trash2 } from 'lucide-react'
import { useOptions } from '../../../hooks/useOptions'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { deleteRecording, setRecordingStage } from '../api'
import { groupStageFeedback } from '../feedbackGroups'
import { useArtworkFeedback } from '../useArtworkFeedback'
import AddFeedbackButtons from './AddFeedbackButtons'
import NoteCard from './NoteCard'
import RecordingAiStatus from './RecordingAiStatus'
import RecordingPlayer from './RecordingPlayer'
import styles from './FeedbackTimeline.module.css'

/**
 * 단계별 피드백 화면의 목록 (아카이브 상세 → 피드백 보기).
 * stageId가 있으면: 위에서 고른 사진(photos[photoIndex])에 연결된 피드백만, 그 아래 단계 공통 피드백
 * (이 단계 사진과 연결되지 않은 피드백). stageId가 없으면 작품 전체 피드백 전부.
 * stages: [{ stageId, title }] 지금 보이는 단계 (녹음의 연결 단계 바꾸기·숨긴 단계 판단)
 * renderFeedbackExtras({ type, id, image_refs }, stageId, reload): 피드백 아래 (기준 사진 확인·변경)
 */
export default function FeedbackList({
  artworkId,
  stageId = null,
  stages,
  photos = [],
  photoIndex = 0,
  renderFeedbackExtras,
}) {
  const options = useOptions()
  const { items, error, reload, reloadRecordings, reloadNotes } = useArtworkFeedback(artworkId)
  const [busyId, setBusyId] = useState(null)
  const [actionError, setActionError] = useState('')
  const stageIds = new Set(stages.map((s) => s.stageId))

  if (error) {
    return (
      <p className={styles.error}>
        피드백을 불러오지 못했어요. {toErrorMessage(error)}{' '}
        <button type="button" className={styles.retry} onClick={reload}>
          다시 시도
        </button>
      </p>
    )
  }
  if (!items) return <p className={styles.caption}>피드백을 불러오는 중…</p>

  async function run(id, action) {
    setBusyId(id)
    setActionError('')
    try {
      await action()
      reloadRecordings()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  function handleDelete(recording) {
    if (!window.confirm('이 녹음을 삭제할까요? 삭제하면 되돌릴 수 없어요.')) return
    run(recording.id, () => deleteRecording(artworkId, recording.id))
  }

  const moveRecording = (recording, next) =>
    run(recording.id, () => setRecordingStage(artworkId, recording.id, next || null))

  const current = photos[Math.min(photoIndex, photos.length - 1)] ?? null
  const groups = groupStageFeedback(items, {
    stageId,
    stageIds,
    photoIds: photos.map((p) => p.id),
  })

  const recordingNode = (recording) => (
    <div className={styles.recording}>
      <span className={styles.label}>
        <Mic size={16} aria-hidden />
        {recording.title ?? '피드백 녹음'}
      </span>
      <div className={styles.row}>
        <RecordingPlayer artworkId={artworkId} recording={recording} />
        <button
          type="button"
          className={styles.delete}
          onClick={() => handleDelete(recording)}
          disabled={busyId === recording.id}
          aria-label="녹음 삭제"
        >
          <Trash2 size={18} />
        </button>
      </div>
      <RecordingAiStatus artworkId={artworkId} recording={recording} />
      {stages.length > 0 && (
        <label className={styles.stageSelect}>
          <span>연결 단계</span>
          <select
            value={recording.stage_id && stageIds.has(recording.stage_id) ? recording.stage_id : ''}
            onChange={(e) => moveRecording(recording, e.target.value)}
            disabled={busyId === recording.id}
          >
            <option value="">작품 전체</option>
            {stages.map((s) => (
              <option key={s.stageId} value={s.stageId}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  )

  const list = (entries) => (
    <ol className={styles.timeline}>
      {entries.map((item) => (
        <li key={item.key} className={styles.entry}>
          {item.time && <span className={styles.time}>{formatUploadedAt(item.time)}</span>}
          <div className={styles.feedback}>
            {item.type === 'RECORDING' ? (
              recordingNode(item.recording)
            ) : (
              <NoteCard note={item.note} options={options} onChanged={reloadNotes} />
            )}
            {renderFeedbackExtras?.(
              { type: item.type, id: item.id, image_refs: item.imageRefs },
              stageId,
              reload,
            )}
          </div>
        </li>
      ))}
    </ol>
  )

  const empty = (text) => <p className={styles.empty}>{text}</p>

  // 작품 전체 피드백
  if (!stageId) {
    return (
      <div className={styles.section}>
        <div className={styles.listHead}>
          <h2 className={styles.heading}>작품 전체 피드백 {groups.total}개</h2>
          <AddFeedbackButtons artworkId={artworkId} compact />
        </div>
        {actionError && <p className={styles.error}>{actionError}</p>}
        {groups.common.length
          ? list(groups.common)
          : empty('아직 작품 전체 피드백이 없어요. 녹음하거나 글로 남겨 보세요.')}
      </div>
    )
  }

  const photoFeedback = current ? groups.byPhoto.get(current.id) : []
  const single = photos.length === 1
  return (
    <div className={styles.section}>
      {actionError && <p className={styles.error}>{actionError}</p>}
      {current && (
        <section className={styles.group} aria-label="이 사진 피드백">
          <div className={styles.listHead}>
            <h2 className={styles.heading}>
              {single ? '이 사진 피드백' : `${photoIndex + 1}번째 사진 피드백`}{' '}
              <span className={styles.headingCount}>{photoFeedback.length}개</span>
            </h2>
            <AddFeedbackButtons
              artworkId={artworkId}
              stageId={stageId}
              photoId={current.id}
              compact
            />
          </div>
          {photoFeedback.length
            ? list(photoFeedback)
            : empty('이 사진에 연결된 피드백이 없어요.')}
        </section>
      )}
      {(groups.common.length > 0 || !current) && (
        <section className={styles.group} aria-label="단계 공통 피드백">
          <div className={styles.listHead}>
            <h2 className={styles.heading}>
              단계 공통 피드백 <span className={styles.headingCount}>{groups.common.length}개</span>
            </h2>
            {!current && <AddFeedbackButtons artworkId={artworkId} stageId={stageId} compact />}
          </div>
          <p className={styles.caption}>이 단계의 특정 사진과 연결되지 않은 피드백이에요.</p>
          {groups.common.length ? list(groups.common) : empty('아직 이 단계 피드백이 없어요.')}
        </section>
      )}
    </div>
  )
}

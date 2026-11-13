import { useCallback, useState } from 'react'
import { Mic, PenLine, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { deleteRecording, listRecordings, setRecordingStage } from '../api'
import { listNotes } from '../notesApi'
import NoteCard from './NoteCard'
import RecordingAiStatus from './RecordingAiStatus'
import RecordingPlayer from './RecordingPlayer'
import styles from './FeedbackTimeline.module.css'

/** 오래된 순 (문자열 비교는 시간대 표기가 섞이면 틀리므로 시각으로 비교) */
const byTime = (a, b) => Date.parse(a.time) - Date.parse(b.time)

/**
 * 작품 상세의 단계별 기록 (v0.9.7)
 * 단계마다 [단계 사진(section.node) → 그 단계의 피드백(녹음·글 첨삭) → 피드백별 수정 사진],
 * 맨 아래에 단계를 정하지 않은 '작품 전체 피드백'.
 * sections: [{ key, stageId, title, node }] — stageId가 없으면(예전 응답) 모든 피드백이 전체 피드백으로
 * renderRevisions({ type, id }, stageId): 피드백 아래 수정 사진 영역 (작품 기능에서 주입)
 */
export default function FeedbackTimeline({ artworkId, sections, renderRevisions }) {
  const options = useOptions()
  const load = useCallback(() => listRecordings(artworkId), [artworkId])
  const { data, reload } = useAsync(load)
  const loadNotes = useCallback(() => listNotes(artworkId), [artworkId])
  const { data: notes, reload: reloadNotes } = useAsync(loadNotes)
  const [busyId, setBusyId] = useState(null)
  const [actionError, setActionError] = useState('')
  const stageIds = new Set(sections.map((s) => s.stageId).filter(Boolean))
  const stageOptions = sections.filter((s) => s.stageId)

  async function run(id, action) {
    setBusyId(id)
    setActionError('')
    try {
      await action()
      reload()
    } catch (error) {
      setActionError(toErrorMessage(error))
    } finally {
      setBusyId(null)
    }
  }

  function handleDelete(recording) {
    if (!window.confirm('이 녹음을 삭제할까요? 삭제하면 되돌릴 수 없어요.')) return
    run(recording.id, () => deleteRecording(artworkId, recording.id))
  }

  const moveRecording = (recording, stageId) =>
    run(recording.id, () => setRecordingStage(artworkId, recording.id, stageId || null))

  // 숨긴 단계(목록에 없는 단계)의 피드백도 잃어버리지 않게 전체 피드백 쪽에 보여 줌
  const stageOf = (item) => (item.stage_id && stageIds.has(item.stage_id) ? item.stage_id : null)

  // 이 API는 페이지 객체가 아니라 배열을 그대로 돌려줌
  const recordingItems = (data ?? []).map((recording) => ({
    key: recording.id,
    stageId: stageOf(recording),
    time: recording.recorded_at ?? recording.uploaded_at ?? recording.created_at,
    feedback: { type: 'RECORDING', id: recording.id },
    node: (
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
        {stageOptions.length > 0 && (
          <label className={styles.stageSelect}>
            <span>연결 단계</span>
            <select
              value={stageOf(recording) ?? ''}
              onChange={(e) => moveRecording(recording, e.target.value)}
              disabled={busyId === recording.id}
            >
              <option value="">작품 전체</option>
              {stageOptions.map((s) => (
                <option key={s.stageId} value={s.stageId}>
                  {s.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    ),
  }))

  // 이 API도 배열을 그대로 돌려줌
  const noteItems = (notes ?? []).map((note) => ({
    key: note.id,
    stageId: stageOf(note),
    time: note.created_at,
    feedback: { type: 'NOTE', id: note.id },
    node: <NoteCard note={note} options={options} onChanged={reloadNotes} />,
  }))

  const all = [...recordingItems, ...noteItems]
  const feedbackOf = (stageId) => all.filter((item) => item.stageId === stageId).sort(byTime)

  const feedbackList = (items, stageId) =>
    items.length > 0 && (
      <ol className={styles.timeline}>
        {items.map((item) => (
          <li key={item.key} className={styles.entry}>
            <span className={styles.time}>{formatUploadedAt(item.time)}</span>
            <div className={styles.feedback}>
              {item.node}
              {renderRevisions?.(item.feedback, stageId)}
            </div>
          </li>
        ))}
      </ol>
    )

  const addButtons = (stageId, compact) => {
    const query = stageId ? `?stage=${stageId}` : ''
    return (
      <div className={`${styles.buttons} ${compact ? styles.compact : ''}`}>
        <Link to={`/artworks/${artworkId}/recordings/new${query}`} className={styles.recordButton}>
          <Mic size={compact ? 18 : 22} aria-hidden />
          {compact ? '녹음' : '피드백 녹음'}
        </Link>
        <Link to={`/artworks/${artworkId}/notes/new${query}`} className={styles.recordButton}>
          <PenLine size={compact ? 18 : 22} aria-hidden />
          {compact ? '글 첨삭' : '글로 첨삭 남기기'}
        </Link>
      </div>
    )
  }

  const overall = feedbackOf(null)
  const staged = stageIds.size > 0

  return (
    <section className={styles.section}>
      {sections.map((section) => {
        const items = section.stageId ? feedbackOf(section.stageId) : []
        return (
          <section key={section.key} className={styles.stage} aria-label={section.title}>
            {section.node}
            {section.stageId && (
              <>
                {items.length > 0 && (
                  <span className={styles.subhead}>
                    {section.title} 피드백 {items.length}개
                  </span>
                )}
                {feedbackList(items, section.stageId)}
                {addButtons(section.stageId, true)}
              </>
            )}
          </section>
        )
      })}

      <section className={styles.stage} aria-label="작품 전체 피드백">
        <h2 className={styles.heading}>{staged ? '작품 전체 피드백' : '피드백'}</h2>
        {staged && (
          <p className={styles.caption}>특정 단계가 아닌 작품 전체에 대한 피드백이에요.</p>
        )}
        {feedbackList(overall, null)}
        {actionError && <p className={styles.error}>{actionError}</p>}
        {addButtons(null, false)}
      </section>
    </section>
  )
}

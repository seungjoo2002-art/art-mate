import { useCallback, useState } from 'react'
import { Image as ImageIcon, Mic } from 'lucide-react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../components/layout/FullScreenStatus'
import TopBar from '../../components/layout/TopBar'
import { Button, Card, Chip, Textarea } from '../../components/ui'
import { deleteArtwork, getArtwork, uploadStagePhoto } from '../../features/artworks/api'
import {
  DEFAULT_STAGE_TARGETS,
  EXAM_PHOTO_STAGES,
  formatClock,
  formatDurationSeconds,
  formatMinutes,
  loadExamSession,
  newExamSession,
  saveExamSession,
  stageSeconds,
} from '../../features/artworks/exam'
import { createNote } from '../../features/feedback/notesApi'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { toErrorMessage } from '../../utils/errorMessages'
import { useExamTimer } from './useExamTimer'
import styles from './Exam.module.css'

/**
 * 실기시험 진행 (/artworks/:artworkId/exam)
 * 전체 시간은 서버 타이머, 단계 구분은 이 기기의 시험 기록(exam session)으로 계산
 */
export default function ExamProgressPage() {
  const { artworkId } = useParams()
  const load = useCallback(() => getArtwork(artworkId), [artworkId])
  const { data: artwork, error, reload } = useAsync(load)
  const timer = useExamTimer(artworkId)

  if (error || timer.error) {
    return (
      <FullScreenStatus
        title="시험 정보를 불러오지 못했어요"
        description={toErrorMessage(error ?? timer.error)}
      />
    )
  }
  if (!artwork || !timer.timer) return <FullScreenStatus />
  if (timer.timer.state === 'STOPPED') {
    return <Navigate to={`/artworks/${artworkId}/exam/result`} replace />
  }
  return <ExamProgress artwork={artwork} timer={timer} onPhotoChanged={reload} />
}

function ExamProgress({ artwork, timer, onPhotoChanged }) {
  const navigate = useNavigate()
  const options = useOptions()
  // 다른 기기에서 열었으면 기록이 없으니 기본 목표로 새로 시작 (단계 시작은 지금 경과 시간부터)
  const [session, setSession] = useState(
    () =>
      loadExamSession(artwork.id) ?? {
        ...newExamSession(DEFAULT_STAGE_TARGETS),
        stageStarts: [timer.elapsed],
      },
  )
  const [memo, setMemo] = useState('')
  const [memoSource, setMemoSource] = useState('SELF_NOTE')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [actionError, setActionError] = useState('')

  const index = session.stageStarts.length - 1
  const stage = session.targets[index]
  const last = index === session.targets.length - 1
  const { elapsed, limitSeconds } = timer
  const remaining = limitSeconds - elapsed
  const stageElapsed = stageSeconds(session, elapsed)[index]
  const typeLabel =
    artwork.practical_type && options
      ? labelOf(options.practical_types, artwork.practical_type)
      : null
  const photoStage = EXAM_PHOTO_STAGES[index]
  const summary = artwork.stages.find((s) => s.stage === photoStage)
  const photo = artwork.photos.find((p) => p.id === summary?.representative_photo_id)

  const update = (next) => {
    setSession(next)
    saveExamSession(artwork.id, next)
  }

  /** 입력한 메모를 이 단계의 글 첨삭으로 저장 */
  async function saveMemo() {
    if (!memo.trim()) return session
    const note = await createNote(artwork.id, {
      source: memoSource,
      body: memo.trim(),
      requestSummary: false,
    })
    setMemo('')
    const next = {
      ...session,
      notes: { ...session.notes, [index]: [...(session.notes[index] ?? []), note.id] },
    }
    update(next)
    return next
  }

  async function run(action) {
    setBusy(true)
    setActionError('')
    try {
      await action()
    } catch (err) {
      setActionError(toErrorMessage(err))
      setBusy(false)
    }
  }

  const nextStage = () =>
    run(async () => {
      const saved = await saveMemo()
      update({ ...saved, stageStarts: [...saved.stageStarts, elapsed] })
      setBusy(false)
      window.scrollTo({ top: 0 })
    })

  const finish = () =>
    run(async () => {
      const saved = await saveMemo()
      const stopped = await timer.send('STOP')
      update({ ...saved, finishedElapsed: stopped.elapsed_seconds })
      navigate(`/artworks/${artwork.id}/exam/result`, { replace: true })
    })

  const cancel = () => {
    if (!window.confirm('시험을 취소할까요? 이 시험 작품과 올린 사진·메모가 모두 삭제돼요.')) return
    run(async () => {
      await deleteArtwork(artwork.id)
      navigate('/practice', { replace: true })
    })
  }

  async function handlePhoto(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUploading(true)
    setActionError('')
    try {
      await uploadStagePhoto(artwork.id, photoStage, file, { replacesPhotoId: photo?.id })
      onPhotoChanged()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <TopBar title="실기시험 진행" belowHeader plain />
      <main className={styles.body}>
        <p className={styles.lead}>
          {[artwork.title, typeLabel, `${index + 1}/${session.targets.length}단계`]
            .filter(Boolean)
            .join(' · ')}
        </p>

        <Card className={styles.clockCard}>
          <div className={styles.clockHead}>
            <span>전체 남은 시간</span>
            <span>총 목표 {formatMinutes(limitSeconds / 60)}</span>
          </div>
          <span className={`${styles.clock} ${remaining < 0 ? styles.over : ''}`} role="timer">
            {remaining < 0 ? '+' : ''}
            {formatClock(remaining)}
          </span>
          <span className={styles.clockSub}>
            경과 {formatClock(elapsed)}
            {remaining < 0 && ' · 목표 시간을 넘겼어요'}
          </span>
          <span className={styles.bar} aria-hidden>
            <span
              style={{ width: `${Math.min(100, (elapsed / Math.max(1, limitSeconds)) * 100)}%` }}
            />
          </span>
        </Card>

        <div className={styles.stageChips} aria-label="시험 단계">
          {session.targets.map((t, i) => (
            <span
              key={t.key}
              className={`${styles.stageChip} ${i === index ? styles.current : ''} ${i < index ? styles.done : ''}`}
            >
              {i + 1}. {t.label}
            </span>
          ))}
        </div>

        <Card className={styles.list}>
          <div className={styles.row}>
            <span className={styles.rowLabel}>현재 단계</span>
            <strong>{stage.label}</strong>
          </div>
          <div className={styles.row}>
            <span className={styles.rowLabel}>단계 목표 / 실제</span>
            <span>
              <strong>{formatMinutes(stage.minutes)}</strong> /{' '}
              <span className={stageElapsed > stage.minutes * 60 ? styles.overText : styles.muted}>
                {formatDurationSeconds(stageElapsed)}
              </span>
            </span>
          </div>
        </Card>

        <section className={styles.section}>
          <h2 className={styles.label}>{stage.label} 단계 사진</h2>
          <label className={styles.upload} aria-busy={uploading}>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className={styles.fileInput}
              onChange={handlePhoto}
              disabled={uploading}
            />
            {photo?.url ? (
              <img src={photo.url} alt={`${stage.label} 단계 사진`} className={styles.photo} />
            ) : (
              <>
                <ImageIcon size={28} aria-hidden />
                <span>{uploading ? '올리는 중…' : '사진 촬영 또는 업로드'}</span>
                <span className={styles.small}>이 단계의 사진으로 저장됩니다</span>
              </>
            )}
          </label>
          {photo && <p className={styles.small}>사진을 누르면 다시 올릴 수 있어요.</p>}
        </section>

        <section className={styles.section}>
          <h2 className={styles.label}>음성 첨삭 녹음</h2>
          <Button onClick={() => navigate(`/artworks/${artwork.id}/recordings/new`)}>
            <Mic size={22} aria-hidden /> 음성 피드백 녹음하기
          </Button>
          <p className={styles.small}>
            녹음 동의가 필요해요. 녹음하는 동안에도 시험 시간은 계속 흘러요.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.label}>{stage.label} 단계 텍스트 메모</h2>
          <div className={styles.chips} role="radiogroup" aria-label="메모 종류">
            <Chip
              role="radio"
              aria-checked={memoSource === 'SELF_NOTE'}
              selected={memoSource === 'SELF_NOTE'}
              onClick={() => setMemoSource('SELF_NOTE')}
            >
              내 메모
            </Chip>
            <Chip
              role="radio"
              aria-checked={memoSource === 'INSTRUCTOR'}
              selected={memoSource === 'INSTRUCTOR'}
              onClick={() => setMemoSource('INSTRUCTOR')}
            >
              선생님 첨삭
            </Chip>
          </div>
          <Textarea
            aria-label={`${stage.label} 단계 메모`}
            rows={4}
            maxLength={5000}
            placeholder="선생님의 첨삭, 스스로 느낀 점 등을 기록하세요."
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
          />
          <p className={styles.small}>다음 단계로 넘어가거나 시험을 완료할 때 저장돼요.</p>
        </section>

        {actionError && <p className={styles.error}>{actionError}</p>}
        <div className={styles.buttons}>
          <Button variant="soft" className={styles.outline} onClick={cancel} disabled={busy}>
            취소
          </Button>
          {last ? (
            <Button onClick={finish} disabled={busy}>
              시험 완료하기
            </Button>
          ) : (
            <Button withArrow onClick={nextStage} disabled={busy}>
              다음 단계 기록
            </Button>
          )}
        </div>
        {!last && (
          <Button variant="soft" onClick={finish} disabled={busy}>
            지금 시험 완료하고 결과 보기
          </Button>
        )}
      </main>
    </>
  )
}

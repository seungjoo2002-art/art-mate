import { useCallback, useState } from 'react'
import { Image as ImageIcon, Mic } from 'lucide-react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../components/layout/FullScreenStatus'
import TopBar from '../../components/layout/TopBar'
import { Button, Card, Chip, Textarea } from '../../components/ui'
import { deleteArtwork, getArtwork, uploadStagePhoto } from '../../features/artworks/api'
import {
  EXAM_PHOTO_STAGE,
  artworkStageFor,
  examStageName,
  formatClock,
  formatDurationSeconds,
  formatMinutes,
  liveStageSeconds,
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
 * 전체 시간(타이머)과 단계 진행(/exam)은 모두 서버 기준 → 다른 기기에서 열어도 같은 단계·시간
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
  if (!artwork || !timer.exam) return <FullScreenStatus />
  if (timer.timer.state === 'STOPPED') {
    return <Navigate to={`/artworks/${artworkId}/exam/result`} replace />
  }
  return <ExamProgress artwork={artwork} timer={timer} onPhotoChanged={reload} />
}

function ExamProgress({ artwork, timer, onPhotoChanged }) {
  const navigate = useNavigate()
  const options = useOptions()
  const [memo, setMemo] = useState('')
  const [memoSource, setMemoSource] = useState('SELF_NOTE')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [actionError, setActionError] = useState('')

  const { exam, elapsed, limitSeconds } = timer
  const stages = exam.stages
  // 예전 버전에서 계획 없이 시작한 시험이면 단계가 없음 → 전체 시간만 보여 주고 완료만 가능
  const index = stages.findIndex((s) => s.status === 'ACTIVE')
  const stage = stages[index] ?? null
  const last = !stage || index === stages.length - 1
  const remaining = limitSeconds - elapsed
  const stageElapsed = stage ? liveStageSeconds(exam, elapsed)[index] : 0
  // v0.9.7: 시험 단계 i = 작품 단계 i → 학생이 정한 이름, 사진·메모·녹음을 그 단계에 연결
  const artworkStage = stage ? artworkStageFor(artwork, stages, index) : null
  const stageId = artworkStage?.id
  const stageLabel = stage ? examStageName(artwork, stages, index) : '시험'
  const typeLabel =
    artwork.practical_type && options
      ? labelOf(options.practical_types, artwork.practical_type)
      : null
  // 대응하는 작품 단계가 없으면(예전 시험) 예전 고정 사진 단계
  const photoStage = stageId ?? EXAM_PHOTO_STAGE[stage?.stage] ?? 'FINAL'
  const photo = stageId
    ? artwork.photos.find(
        (p) => p.stage_id === stageId && (p.kind ?? 'STAGE') === 'STAGE' && p.is_representative,
      )
    : artwork.photos.find(
        (p) => p.id === artwork.stages.find((s) => s.stage === photoStage)?.representative_photo_id,
      )

  /** 입력한 메모를 이 단계의 글 첨삭으로 저장 (단계 연결이 없으면 결과 화면에서 작성 시각으로 나눔) */
  async function saveMemo() {
    if (!memo.trim()) return
    await createNote(artwork.id, {
      source: memoSource,
      body: memo.trim(),
      requestSummary: false,
      stageId, // v0.9.7 이 단계의 피드백으로
    })
    setMemo('')
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
      await saveMemo()
      try {
        await timer.next(stage.stage)
      } catch (err) {
        // 다른 기기·탭에서 이미 넘겼거나 마지막 단계면 서버 상태로 맞춤
        if (['EXAM_STAGE_CONFLICT', 'EXAM_LAST_STAGE'].includes(err.code)) await timer.reload()
        throw err
      }
      setBusy(false)
      window.scrollTo({ top: 0 })
    })

  const finish = () =>
    run(async () => {
      await saveMemo()
      await timer.send('STOP')
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
          {[artwork.title, typeLabel, stage && `${index + 1}/${stages.length}단계`]
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

        {stage && (
          <>
            <div className={styles.stageChips} aria-label="시험 단계">
              {stages.map((t, i) => (
                <span
                  key={t.stage}
                  className={`${styles.stageChip} ${t.status === 'ACTIVE' ? styles.current : ''} ${t.status === 'DONE' ? styles.done : ''}`}
                >
                  {i + 1}. {examStageName(artwork, stages, i)}
                </span>
              ))}
            </div>

            <Card className={styles.list}>
              <div className={styles.row}>
                <span className={styles.rowLabel}>현재 단계</span>
                <strong>{stageLabel}</strong>
              </div>
              <div className={styles.row}>
                <span className={styles.rowLabel}>단계 목표 / 실제</span>
                <span>
                  <strong>{formatMinutes(stage.target_minutes)}</strong> /{' '}
                  <span
                    className={
                      stageElapsed > stage.target_minutes * 60 ? styles.overText : styles.muted
                    }
                  >
                    {formatDurationSeconds(stageElapsed)}
                  </span>
                </span>
              </div>
            </Card>
          </>
        )}

        <section className={styles.section}>
          <h2 className={styles.label}>{stageLabel} 단계 사진</h2>
          <label className={styles.upload} aria-busy={uploading}>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className={styles.fileInput}
              onChange={handlePhoto}
              disabled={uploading}
            />
            {photo?.url ? (
              <img src={photo.url} alt={`${stageLabel} 단계 사진`} className={styles.photo} />
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
          <Button
            onClick={() =>
              navigate(
                `/artworks/${artwork.id}/recordings/new${stageId ? `?stage=${stageId}` : ''}`,
              )
            }
          >
            <Mic size={22} aria-hidden /> 음성 피드백 녹음하기
          </Button>
          <p className={styles.small}>
            녹음 동의가 필요해요. 녹음하는 동안에도 시험 시간은 계속 흘러요.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.label}>{stageLabel} 단계 텍스트 메모</h2>
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
            aria-label={`${stageLabel} 단계 메모`}
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

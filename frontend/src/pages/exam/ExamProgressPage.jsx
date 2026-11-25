import { useCallback, useState } from 'react'
import { ImagePlus, Mic } from 'lucide-react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../components/layout/FullScreenStatus'
import TopBar from '../../components/layout/TopBar'
import Highlight from '../../components/decor/Highlight'
import PaintSplash from '../../components/decor/PaintSplash'
import MascotCheer from '../../components/mascot/MascotCheer'
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
import StagePath from '../../features/artworks/components/StagePath'
import { tabColor, tabLabel } from '../../features/artworks/sectionTabs'
import tabStyles from '../../features/artworks/SectionTabs.module.css'
import { createNote } from '../../features/feedback/notesApi'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { toErrorMessage } from '../../utils/errorMessages'
import { useExamTimer } from './useExamTimer'
import styles from './Exam.module.css'
import { IMAGE_ACCEPT } from '../../lib/imageFile'

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
  const [photoError, setPhotoError] = useState('') // 사진 칸 바로 아래에 보여 줌

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
    setPhotoError('')
    try {
      await uploadStagePhoto(artwork.id, photoStage, file, { replacesPhotoId: photo?.id })
      onPhotoChanged()
    } catch (err) {
      setPhotoError(toErrorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <TopBar title="실기시험 진행" belowHeader plain />
      <main className={styles.body}>
        {/* 서 있는 고양이 응원 */}
        <MascotCheer
          pose={remaining < 0 ? 'worried' : 'cheer'}
          sub={[artwork.title, typeLabel, stage && `${index + 1}/${stages.length}단계`]
            .filter(Boolean)
            .join(' · ')}
        >
          {remaining < 0 ? (
            <>
              목표 시간을 넘겼어요. <Highlight>마무리</Highlight>해 볼까요?
            </>
          ) : stage ? (
            <>
              지금은 <Highlight>{stageLabel} 단계</Highlight>! 집중해서 그려 봐요
            </>
          ) : (
            <>
              <Highlight>집중해서</Highlight> 그려 봐요
            </>
          )}
          <PaintSplash />
        </MascotCheer>

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

          {/* 단계 길: 지난 단계 ✓, 지금 단계 테두리, 남은 단계 흐리게 */}
          {stage && (
            <div className={styles.stagePath}>
              <StagePath
                label="시험 단계"
                current={index}
                stages={stages.map((t, i) => ({ key: t.stage, name: examStageName(artwork, stages, i) }))}
              />
              <p className={styles.stageNow}>
                지금 <strong>{stageLabel}</strong> · 목표 {formatMinutes(stage.target_minutes)} /{' '}
                <span
                  className={stageElapsed > stage.target_minutes * 60 ? styles.overText : undefined}
                >
                  {formatDurationSeconds(stageElapsed)}
                </span>
              </p>
            </div>
          )}
        </Card>

        <section className={tabStyles.card} style={{ '--tab': tabColor(1) }}>
          <h2 className={tabStyles.tab}>{tabLabel(1, `${stageLabel} 단계 사진`)}</h2>
          <label className={`${styles.upload} ${photo?.url ? styles.hasPhoto : ''}`} aria-busy={uploading}>
            <input
              type="file"
              accept={IMAGE_ACCEPT}
              className={styles.fileInput}
              onChange={handlePhoto}
              disabled={uploading}
            />
            {photo?.url ? (
              <img src={photo.url} alt={`${stageLabel} 단계 사진`} className={styles.photo} />
            ) : (
              <>
                <span className={styles.uploadIcon}>
                  <ImagePlus size={22} aria-hidden />
                </span>
                <span className={styles.uploadTitle}>{uploading ? '올리는 중…' : '사진 올리기'}</span>
                <span className={styles.small}>탭해서 촬영하거나 앨범에서 골라요</span>
              </>
            )}
          </label>
          {photoError && (
            <p
              className={styles.error}
              role="alert"
              ref={(el) => el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })}
            >
              {photoError}
            </p>
          )}
          {photo && <p className={styles.small}>사진을 누르면 다시 올릴 수 있어요.</p>}
        </section>

        <section className={tabStyles.card} style={{ '--tab': tabColor(2) }}>
          <h2 className={tabStyles.tab}>{tabLabel(2, '음성 첨삭')}</h2>
          <div className={styles.recordRow}>
            {/* 마이크 아이콘만 크게. 화면 낭독기·툴팁은 "음성 피드백 녹음하기" */}
            <button
              type="button"
              className={styles.micButton}
              aria-label="음성 피드백 녹음하기"
              title="음성 피드백 녹음하기"
              onClick={() =>
                navigate(
                  `/artworks/${artwork.id}/recordings/new${stageId ? `?stage=${stageId}` : ''}`,
                )
              }
            >
              <Mic size={26} aria-hidden />
            </button>
            <p className={styles.small}>
              녹음 동의가 필요해요. 녹음하는 동안에도 시험 시간은 계속 흘러요.
            </p>
          </div>
        </section>

        <section className={tabStyles.card} style={{ '--tab': tabColor(3) }}>
          <h2 className={tabStyles.tab}>{tabLabel(3, '텍스트 메모')}</h2>
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
        {/* 주 버튼은 화면 아래에 늘 보이게, 나머지는 작은 글자 버튼 */}
        <div className={styles.actionBar}>
          {last ? (
            <Button size="compact" onClick={finish} disabled={busy}>
              시험 완료하기
            </Button>
          ) : (
            <Button size="compact" withArrow onClick={nextStage} disabled={busy}>
              다음 단계 기록
            </Button>
          )}
          <div className={styles.textActions}>
            {!last && (
              <button type="button" onClick={finish} disabled={busy}>
                지금 완료하고 결과 보기
              </button>
            )}
            <button type="button" className={styles.cancel} onClick={cancel} disabled={busy}>
              시험 취소
            </button>
          </div>
        </div>
      </main>
    </>
  )
}

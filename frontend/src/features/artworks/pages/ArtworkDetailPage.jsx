import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  completeArtwork,
  deleteArtwork,
  deletePhoto,
  getArtwork,
  reopenArtwork,
  uploadStagePhoto,
} from '../api'
import RevisionPhotos from '../components/RevisionPhotos'
import StagePhotoCard from '../components/StagePhotoCard'
import StageStepper from '../components/StageStepper'
import {
  hasFinalPhoto,
  isCompleted,
  revisionPhotosOf,
  stagesWithPhotos,
  unlinkedRevisions,
} from '../stages'
import { formatMinutes } from '../exam'
import styles from './ArtworkPage.module.css'

/**
 * renderTimeline({ artworkId, sections, renderRevisions }): 단계마다 [사진 카드 → 단계 피드백 →
 * 피드백별 수정 사진], 맨 아래 작품 전체 피드백을 그리는 함수 (v0.9.7).
 * features끼리 직접 import하지 않도록 라우터에서 주입. 없으면 단계 사진만 순서대로 그림
 */
export default function ArtworkDetailPage({ renderTimeline }) {
  const { artworkId } = useParams()
  const navigate = useNavigate()
  const load = useCallback(() => getArtwork(artworkId), [artworkId])
  const { data: artwork, error, reload } = useAsync(load)
  const [busyStage, setBusyStage] = useState(null) // 업로드·삭제 중인 단계
  const [actionError, setActionError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [statusBusy, setStatusBusy] = useState(false)
  const options = useOptions()

  if (error) {
    return (
      <FullScreenStatus title="작품을 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!artwork) return <FullScreenStatus />

  const stages = stagesWithPhotos(artwork)
  const completed = isCompleted(artwork)
  const finalPhoto = hasFinalPhoto(artwork)

  async function runStageAction(stage, action) {
    if (busyStage) return
    setBusyStage(stage.key)
    setActionError('')
    try {
      await action()
      reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusyStage(null)
    }
  }

  // 단계당 대표 사진 1장으로 보여 주므로, 이미 있으면 교체 (단계 id가 없으면 예전 고정 단계 값)
  const handleSelectFile = (stage, file) =>
    runStageAction(stage, () =>
      uploadStagePhoto(artwork.id, stage.id ?? stage.legacy, file, {
        replacesPhotoId: stage.photo?.id,
      }),
    )

  function handleDeletePhoto(stage) {
    if (!window.confirm(`${stage.photoLabel}을 삭제할까요?`)) return
    runStageAction(stage, () => deletePhoto(artwork.id, stage.photo.id))
  }

  /** 작품 완료 / 작업 재개 */
  async function setStatus(action) {
    setStatusBusy(true)
    setActionError('')
    try {
      await action(artwork.id)
      reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setStatusBusy(false)
    }
  }

  async function handleDeleteArtwork() {
    if (!window.confirm('작품을 삭제할까요? 사진과 녹음도 모두 삭제되고 되돌릴 수 없어요.')) return
    setDeleting(true)
    setActionError('')
    try {
      await deleteArtwork(artwork.id)
      navigate('/archive', { replace: true })
    } catch (err) {
      setActionError(toErrorMessage(err))
      setDeleting(false)
    }
  }

  // 단계마다 사진 카드 (+ 피드백이 지워져 연결이 끊긴 수정 사진)
  const sections = stages.map((stage, index) => {
    const orphans = stage.id ? unlinkedRevisions(artwork, stage.id) : []
    return {
      key: stage.key,
      stageId: stage.id,
      title: stage.label,
      node: (
        <>
          <StagePhotoCard
            artworkId={artwork.id}
            stage={stage}
            index={index}
            busy={busyStage === stage.key}
            locked={completed}
            onSelectFile={(file) => handleSelectFile(stage, file)}
            onDelete={() => handleDeletePhoto(stage)}
          />
          {orphans.length > 0 && (
            <RevisionPhotos
              artworkId={artwork.id}
              feedback={{ type: 'NOTE', id: null }}
              photos={orphans}
              stageId={stage.id}
              stages={stages}
              locked
              label="연결된 피드백이 삭제된 수정 사진"
              onChanged={reload}
            />
          )}
        </>
      ),
    }
  })

  const renderRevisions = (feedback, stageId) =>
    stages.some((s) => s.id) && (
      <RevisionPhotos
        artworkId={artwork.id}
        feedback={feedback}
        photos={revisionPhotosOf(artwork, feedback)}
        stageId={stageId}
        stages={stages}
        locked={completed}
        onChanged={reload}
      />
    )

  return (
    <>
      <TopBar
        title={artwork.title}
        belowHeader
        right={
          <span className={`${styles.status} ${completed ? styles.statusDone : ''}`}>
            {completed ? '완성' : '진행 중'}
          </span>
        }
      />
      <main className={styles.body}>
        {/* 실기시험 작품: 진행 중이면 이어서 하기, 끝났으면(STOP으로 actual_minutes 저장) 결과 보기 */}
        {artwork.work_category === 'MOCK_EXAM' &&
          (artwork.actual_minutes ? (
            <Button variant="soft" onClick={() => navigate(`/artworks/${artwork.id}/exam/result`)}>
              시험 결과 보기
            </Button>
          ) : (
            <Button onClick={() => navigate(`/artworks/${artwork.id}/exam`)}>
              시험 이어서 하기
            </Button>
          ))}
        <ArtworkMeta artwork={artwork} options={options} />
        {(artwork.topic || artwork.description) && (
          <Card variant="soft" className={styles.topic}>
            <span className={styles.topicLabel}>오늘의 주제</span>
            <span className={styles.topicText}>{artwork.topic || artwork.description}</span>
          </Card>
        )}

        <StageStepper stages={stages} />

        {renderTimeline ? (
          renderTimeline({ artworkId: artwork.id, sections, renderRevisions })
        ) : (
          <div className={styles.stageList}>
            {sections.map((section) => (
              <div key={section.key}>{section.node}</div>
            ))}
          </div>
        )}
        {actionError && <p className={styles.error}>{actionError}</p>}

        {completed ? (
          <>
            <Button variant="soft" onClick={() => setStatus(reopenArtwork)} disabled={statusBusy}>
              {statusBusy ? '처리하는 중…' : '작업 재개'}
            </Button>
            <p className={styles.hint}>
              완료한 작품은 사진을 바꿀 수 없어요. 녹음과 첨삭은 계속 추가할 수 있어요.
            </p>
          </>
        ) : (
          <>
            <Button onClick={() => setStatus(completeArtwork)} disabled={!finalPhoto || statusBusy}>
              {statusBusy ? '처리하는 중…' : '작품 완료하기'}
            </Button>
            {!finalPhoto && (
              <p className={styles.hint}>
                마지막 단계({stages.at(-1)?.label}) 사진을 올리면 작품을 완료할 수 있어요.
              </p>
            )}
          </>
        )}
        {finalPhoto && (
          <Button variant="soft" onClick={() => navigate(`/community/write?artwork=${artwork.id}`)}>
            커뮤니티에 공유하기
          </Button>
        )}
        <Button variant="soft" onClick={() => navigate(`/artworks/${artwork.id}/edit`)}>
          작품 정보 수정
        </Button>
        <button
          type="button"
          className={styles.deleteArtwork}
          onClick={handleDeleteArtwork}
          disabled={deleting}
        >
          {deleting ? '삭제하는 중…' : '작품 삭제'}
        </button>
      </main>
    </>
  )
}

/** 실기 유형 · 분류 · 작업 방식 · 소요/제한 시간 한 줄 */
function ArtworkMeta({ artwork, options }) {
  const label = (list, code) => (code && options ? labelOf(options[list], code) : null)
  const parts = [
    label('practical_types', artwork.practical_type),
    label('work_categories', artwork.work_category),
    artwork.work_method,
    artwork.actual_minutes && `소요 ${formatMinutes(artwork.actual_minutes)}`,
    artwork.time_limit_minutes && `제한 ${formatMinutes(artwork.time_limit_minutes)}`,
  ].filter(Boolean)
  if (!parts.length) return null
  return <p className={styles.meta}>{parts.join(' · ')}</p>
}

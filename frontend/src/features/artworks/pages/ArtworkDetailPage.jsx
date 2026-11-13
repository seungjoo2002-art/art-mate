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
import StagePhotoCard from '../components/StagePhotoCard'
import StageStepper from '../components/StageStepper'
import AddPhotoButton from '../components/AddPhotoButton'
import ExtraPhotoCard from '../components/ExtraPhotoCard'
import { STAGES, hasFinalPhoto, isCompleted, stagesWithPhotos } from '../stages'
import { formatMinutes } from '../exam'
import styles from './ArtworkPage.module.css'

/**
 * renderTimeline({ artworkId, items }): 단계 사진 카드(items)에 녹음 등을 시간순으로 섞어 그리는 함수.
 * features끼리 직접 import하지 않도록 라우터에서 주입. 없으면 단계 순서대로 그림
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
  // VER.2 P0: 커뮤니티 공유는 단계 사진 1장만 있어도 가능 (공유할 사진은 글쓰기에서 고름)
  const hasAnyPhoto = (artwork.photos?.length ?? 0) > 0

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

  // 단계당 사진 1장으로 보여 주므로, 이미 있으면 교체
  const handleSelectFile = (stage, file) =>
    runStageAction(stage, () =>
      uploadStagePhoto(artwork.id, stage.key, file, { replacesPhotoId: stage.photo?.id }),
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

  // 대표가 아닌 추가 사진 → 올린 시각으로 타임라인에 (녹음·첨삭과 함께 시간순)
  const extraPhotos = artwork.photos.filter((p) => !p.is_representative && p.status === 'ACTIVE')
  // 추가 사진 기본 단계: 가장 최근에 사진을 올린 단계
  const latestStage =
    artwork.photos
      .filter((p) => p.status === 'ACTIVE')
      .sort(
        (a, b) =>
          Date.parse(b.uploaded_at ?? b.created_at) - Date.parse(a.uploaded_at ?? a.created_at),
      )[0]?.stage ?? 'SKETCH'

  async function handleAddPhoto(stageKey, file) {
    setBusyStage('extra')
    setActionError('')
    try {
      await uploadStagePhoto(artwork.id, stageKey, file)
      reload()
      return true
    } catch (err) {
      setActionError(toErrorMessage(err))
      return false
    } finally {
      setBusyStage(null)
    }
  }

  async function handleDeleteExtra(photo) {
    if (!window.confirm('이 추가 사진을 삭제할까요?')) return
    setBusyStage(photo.id)
    setActionError('')
    try {
      await deletePhoto(artwork.id, photo.id)
      reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusyStage(null)
    }
  }

  const extraItems = extraPhotos.map((photo) => ({
    key: photo.id,
    time: photo.uploaded_at ?? photo.created_at,
    node: (
      <ExtraPhotoCard
        artworkId={artwork.id}
        photo={photo}
        stageLabel={STAGES.find((s) => s.key === photo.stage)?.label ?? photo.stage}
        locked={completed}
        busy={busyStage === photo.id}
        onDelete={() => handleDeleteExtra(photo)}
      />
    ),
  }))

  // 타임라인 항목: 사진이 있는 단계는 업로드 시각, 빈 단계는 시각 없음(맨 뒤)
  const stageItems = stages.map((stage, index) => ({
    key: stage.key,
    time: stage.photo ? stage.uploadedAt : null,
    node: (
      <StagePhotoCard
        key={stage.key}
        artworkId={artwork.id}
        stage={stage}
        index={index}
        busy={busyStage === stage.key}
        locked={completed}
        onSelectFile={(file) => handleSelectFile(stage, file)}
        onDelete={() => handleDeletePhoto(stage)}
      />
    ),
  }))

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
          renderTimeline({
            artworkId: artwork.id,
            items: [...stageItems, ...extraItems],
            // 완료한 작품은 사진을 바꿀 수 없음 (서버도 409 ARTWORK_COMPLETED)
            actions: completed ? null : (
              <AddPhotoButton
                key={latestStage}
                defaultStage={latestStage}
                busy={busyStage === 'extra'}
                onUpload={handleAddPhoto}
              />
            ),
          })
        ) : (
          <div className={styles.stageList}>{stageItems.map((item) => item.node)}</div>
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
              <p className={styles.hint}>완성 사진을 올리면 작품을 완료할 수 있어요.</p>
            )}
          </>
        )}
        {hasAnyPhoto && (
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

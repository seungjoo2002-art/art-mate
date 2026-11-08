import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { deleteArtwork, deletePhoto, getArtwork, uploadStagePhoto } from '../api'
import StagePhotoCard from '../components/StagePhotoCard'
import StageStepper from '../components/StageStepper'
import { isCompleted, stagesWithPhotos } from '../stages'
import styles from './ArtworkPage.module.css'

/** feedbackSection: 녹음 영역 (features끼리 직접 import하지 않도록 라우터에서 주입) */
export default function ArtworkDetailPage({ feedbackSection }) {
  const { artworkId } = useParams()
  const navigate = useNavigate()
  const load = useCallback(() => getArtwork(artworkId), [artworkId])
  const { data: artwork, error, reload } = useAsync(load)
  const [busyStage, setBusyStage] = useState(null) // 업로드·삭제 중인 단계
  const [actionError, setActionError] = useState('')
  const [deleting, setDeleting] = useState(false)

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
        {artwork.description && (
          <Card variant="soft" className={styles.topic}>
            <span className={styles.topicLabel}>오늘의 주제</span>
            <span className={styles.topicText}>{artwork.description}</span>
          </Card>
        )}

        <StageStepper stages={stages} />

        <div className={styles.stageList}>
          {stages.map((stage, index) => (
            <StagePhotoCard
              key={stage.key}
              artworkId={artwork.id}
              stage={stage}
              index={index}
              busy={busyStage === stage.key}
              onSelectFile={(file) => handleSelectFile(stage, file)}
              onDelete={() => handleDeletePhoto(stage)}
            />
          ))}
        </div>
        {actionError && <p className={styles.error}>{actionError}</p>}

        {feedbackSection?.(artwork.id)}
        <Button disabled={!completed} onClick={() => navigate('/archive')}>
          작품 완료하기
        </Button>
        {!completed && <p className={styles.hint}>완성 사진을 올리면 작품을 완료할 수 있어요.</p>}
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

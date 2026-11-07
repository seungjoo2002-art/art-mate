import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getArtwork, uploadStagePhoto } from '../api'
import StagePhotoCard from '../components/StagePhotoCard'
import StageStepper from '../components/StageStepper'
import { isCompleted, stagesWithPhotos } from '../stages'
import styles from './ArtworkPage.module.css'

export default function ArtworkDetailPage() {
  const { artworkId } = useParams()
  const navigate = useNavigate()
  const load = useCallback(() => getArtwork(artworkId), [artworkId])
  const { data: artwork, error, reload } = useAsync(load)
  const [uploadingStage, setUploadingStage] = useState(null)
  const [uploadError, setUploadError] = useState('')

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

  async function handleSelectFile(stage, file) {
    setUploadingStage(stage.key)
    setUploadError('')
    try {
      // 단계당 사진 1장으로 보여 주므로, 이미 있으면 교체
      await uploadStagePhoto(artwork.id, stage.key, file, { replacesPhotoId: stage.photo?.id })
      reload()
    } catch (err) {
      setUploadError(toErrorMessage(err))
    } finally {
      setUploadingStage(null)
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
              uploading={uploadingStage === stage.key}
              onSelectFile={(file) => !uploadingStage && handleSelectFile(stage, file)}
            />
          ))}
        </div>
        {uploadError && <p className={styles.error}>{uploadError}</p>}

        {/* TODO(v0.5): 피드백 녹음 버튼 */}
        <Button disabled={!completed} onClick={() => navigate('/archive')}>
          작품 완료하기
        </Button>
        {!completed && <p className={styles.hint}>완성 사진을 올리면 작품을 완료할 수 있어요.</p>}
      </main>
    </>
  )
}

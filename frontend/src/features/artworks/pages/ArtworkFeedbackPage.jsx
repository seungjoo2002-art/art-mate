import { useCallback, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getArtwork } from '../api'
import FeedbackRefs from '../components/FeedbackRefs'
import PhotoCarousel from '../components/PhotoCarousel'
import PhotoViewer from '../components/PhotoViewer'
import { photoShownAt, stagePhotos, stagesWithPhotos } from '../stages'
import styles from './ArtworkFeedbackPage.module.css'

/**
 * 단계별 피드백 화면 (아카이브 상세 → '단계 피드백 보기' / '작품 전체 피드백 보기').
 * /artworks/:artworkId/feedback?stage=단계 id&photo=사진 id  (stage가 없으면 작품 전체 피드백)
 * 단계: 위에 그 단계 사진 슬라이드, 아래에 지금 고른 사진과 연결된 피드백 + 단계 공통 피드백.
 * renderFeedback({ artworkId, stageId, stages, photos, photoIndex, renderFeedbackExtras }):
 *   피드백 목록 (features끼리 직접 import하지 않도록 라우터에서 주입)
 */
export default function ArtworkFeedbackPage({ renderFeedback }) {
  const { artworkId } = useParams()
  const [params, setParams] = useSearchParams()
  const load = useCallback(() => getArtwork(artworkId), [artworkId])
  const { data: artwork, error, reload } = useAsync(load)
  const [viewer, setViewer] = useState(null)
  const closeViewer = useCallback(() => setViewer(null), [])

  if (error) {
    return (
      <FullScreenStatus title="작품을 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!artwork) return <FullScreenStatus />

  const stages = stagesWithPhotos(artwork)
  const stageOptions = stages.filter((s) => s.id).map((s) => ({ stageId: s.id, title: s.label }))
  // 숨긴 단계·없는 단계 주소면 작품 전체 피드백으로
  const stage = stages.find((s) => s.id && s.id === params.get('stage')) ?? null
  const photos = stage ? stagePhotos(artwork, stage.id) : []
  const found = photos.findIndex((p) => p.id === params.get('photo'))
  const photoIndex = found >= 0 ? found : 0
  const current = photos[photoIndex] ?? null

  // 고른 사진을 주소에 남겨 둠 (첨삭 수정 후 돌아와도 같은 사진)
  const selectPhoto = (i) => {
    const next = new URLSearchParams(params)
    next.set('photo', photos[i].id)
    setParams(next, { replace: true })
  }

  // 피드백 아래: 이 피드백이 근거로 삼은 사진 (확인·변경)
  const refsKey = (feedback) =>
    [feedback.id, feedback.image_refs?.status]
      .concat((feedback.image_refs?.photos ?? []).map((p) => p.photo_id))
      .join('-')
  const renderFeedbackExtras = (feedback, _stageId, reloadFeedback) =>
    stageOptions.length > 0 && (
      <FeedbackRefs
        key={refsKey(feedback)}
        artwork={artwork}
        feedback={feedback}
        stages={stages}
        onChanged={reloadFeedback}
      />
    )

  const title = stage ? `${stage.label} 단계 피드백` : '작품 전체 피드백'

  return (
    <>
      <TopBar title={title} belowHeader />
      <main className={styles.body}>
        <p className={styles.artwork}>{artwork.title}</p>
        {stage &&
          (photos.length ? (
            <section className={styles.photos} aria-label={`${stage.label} 사진`}>
              <PhotoCarousel
                artworkId={artwork.id}
                photos={photos}
                index={photoIndex}
                onIndexChange={selectPhoto}
                alt={`${stage.label} 사진`}
                onOpen={(photo) => setViewer(photo)}
              />
              <p className={styles.photoMeta}>
                {photos.length > 1 && (
                  <span className={styles.order}>
                    {photoIndex + 1}번째 사진 / {photos.length}장
                  </span>
                )}
                <span>{formatUploadedAt(photoShownAt(current))}</span>
              </p>
            </section>
          ) : (
            <p className={styles.noPhoto}>아직 이 단계 사진이 없어요.</p>
          ))}

        {renderFeedback?.({
          artworkId: artwork.id,
          stageId: stage?.id ?? null,
          stages: stageOptions,
          photos,
          photoIndex,
          renderFeedbackExtras,
        })}
      </main>
      <PhotoViewer
        artworkId={artwork.id}
        photo={viewer}
        alt={stage ? `${stage.label} 사진` : ''}
        onClose={closeViewer}
      />
    </>
  )
}

import { useCallback, useState } from 'react'
import { PencilLine, Share2, Trash2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import Highlight from '../../../components/decor/Highlight'
import PaintSplash from '../../../components/decor/PaintSplash'
import MascotCheer from '../../../components/mascot/MascotCheer'
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
import PhotoViewer from '../components/PhotoViewer'
import ReferenceCompare from '../components/ReferenceCompare'
import refStyles from '../components/ReferenceGrid.module.css'
import StageHeader from '../components/StageHeader'
import StagePhotos from '../components/StagePhotos'
import StageStepper from '../components/StageStepper'
import { hasFinalPhoto, isCompleted, stagePhotos, stagesWithPhotos } from '../stages'
import { formatMinutes } from '../exam'
import { artworkConditions, EXPRESSION_METHODS } from '../referencePhotos'
import styles from './ArtworkPage.module.css'

/**
 * 작품 상세 (아카이브): 작품 정보 → 단계마다 [사진 수·사진 추가 → 사진 가로 슬라이드(교체·삭제)
 * → 녹음·글 첨삭 등록 → 단계 피드백 보기] → 작품 전체 피드백.
 * 피드백 내용은 여기 늘어놓지 않고 피드백 보기 화면(/artworks/:id/feedback)에서 본다.
 * renderTimeline({ artworkId, sections }): 단계 묶음과 그 아래 피드백 등록·보기 버튼을 그리는 함수.
 * features끼리 직접 import하지 않도록 라우터에서 주입. 없으면 단계 사진만 그림
 */
/** 사진 오류가 화면 아래쪽에 생겨도 바로 보이게 */
const showAlert = (el) => el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })

export default function ArtworkDetailPage({ renderTimeline }) {
  const { artworkId } = useParams()
  const navigate = useNavigate()
  const load = useCallback(() => getArtwork(artworkId), [artworkId])
  const { data: artwork, error, reload } = useAsync(load)
  // 사진 작업 중인 단계 { stage: 단계 key, upload: 사진 추가 중인지 }
  const [busy, setBusy] = useState(null)
  // 사진 추가·교체·삭제 실패: 그 단계 바로 아래에 보여 줌 { stage: 단계 key, message }
  const [photoError, setPhotoError] = useState(null)
  const [photoIndex, setPhotoIndex] = useState({}) // 단계 key → 슬라이드에서 보는 사진 순서
  const [viewer, setViewer] = useState(null) // 크게 보는 사진 { photo, alt }
  const closeViewer = useCallback(() => setViewer(null), [])
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

  // 사진 올리기·교체·삭제 (한 번에 하나)
  async function run(stage, action, { upload = false, then } = {}) {
    if (busy) return
    setBusy({ stage: stage.key, upload })
    setPhotoError(null)
    try {
      await action()
      then?.()
      reload()
    } catch (err) {
      setPhotoError({ stage: stage.key, message: toErrorMessage(err) })
    } finally {
      setBusy(null)
    }
  }

  // 단계 id가 없으면 예전 고정 단계 값
  const stageValue = (stage) => stage.id ?? stage.legacy
  const indexOf = (stage, count) => Math.min(photoIndex[stage.key] ?? 0, Math.max(count - 1, 0))
  const showPhoto = (stage, i) => setPhotoIndex((prev) => ({ ...prev, [stage.key]: i }))

  // 새 사진은 단계 슬라이드 끝에 붙고, 올린 사진을 바로 보여 줌
  const handleUpload = (stage, file, count) =>
    run(stage, () => uploadStagePhoto(artwork.id, stageValue(stage), file), {
      upload: true,
      then: () => showPhoto(stage, count),
    })

  // 교체: 지금 보는 사진 자리에 (등록 순서·단계·대표 여부 그대로. 교체 전 사진을 본 피드백은 그대로)
  function handleReplace(stage, photo, file) {
    const message =
      '지금 보는 사진을 새로 고른 사진으로 교체할까요?\n' +
      '이 사진을 보고 받은 피드백은 교체 전 사진을 그대로 기억해요.'
    if (!window.confirm(message)) return
    run(stage, () =>
      uploadStagePhoto(artwork.id, stageValue(stage), file, { replacesPhotoId: photo.id }),
    )
  }

  function handleDeletePhoto(stage, photo) {
    if (!window.confirm('이 사진을 삭제할까요? 이 사진을 기준으로 한 피드백 기록은 남아요.')) return
    run(stage, () => deletePhoto(artwork.id, photo.id))
  }

  /** 작품 완성 / 작업 다시 시작 */
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

  const sections = stages.map((stage, index) => {
    // 예전 응답(단계 id 없음)은 예전 고정 단계 값으로 묶음
    const photos = stage.id
      ? stagePhotos(artwork, stage.id)
      : stagePhotos(artwork, null).filter((p) => p.stage === stage.legacy)
    const current = indexOf(stage, photos.length)
    const stageBusy = busy?.stage === stage.key
    return {
      key: stage.key,
      stageId: stage.id,
      title: stage.label,
      photoId: photos[current]?.id, // 새 피드백의 기본 기준 사진
      node: (
        <>
          <StageHeader
            stage={stage}
            index={index}
            photoCount={photos.length}
            busy={stageBusy && busy.upload}
            locked={completed}
            onSelectFile={(file) => handleUpload(stage, file, photos.length)}
          />
          <StagePhotos
            artworkId={artwork.id}
            photos={photos}
            index={current}
            onIndexChange={(i) => showPhoto(stage, i)}
            stageLabel={stage.label}
            locked={completed}
            busy={stageBusy}
            onReplace={(photo, file) => handleReplace(stage, photo, file)}
            onDelete={(photo) => handleDeletePhoto(stage, photo)}
            onOpen={(photo) => setViewer({ photo, alt: `${stage.label} 사진` })}
          />
          {photoError?.stage === stage.key && (
            <p className={styles.error} role="alert" ref={showAlert}>
              {photoError.message}
            </p>
          )}
        </>
      ),
    }
  })

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
        {/* 서 있는 고양이: 진행 상황에 맞춘 한마디 */}
        <MascotCheer
          pose={completed ? 'happy' : finalPhoto ? 'check' : hasAnyPhoto ? 'artist' : 'curious'}
        >
          {completed ? (
            <>
              <Highlight>작품 완성!</Highlight> 정말 수고했어요
            </>
          ) : finalPhoto ? (
            <>
              마지막 사진까지 올렸어요! <Highlight>완료해 볼까요?</Highlight>
            </>
          ) : hasAnyPhoto ? (
            <>
              오늘도 <Highlight>한 단계씩</Highlight> 기록해 봐요
            </>
          ) : (
            <>
              <Highlight>첫 단계 사진</Highlight>부터 올려 볼까요?
            </>
          )}
          <PaintSplash />
        </MascotCheer>
        {/* 실기시험 작품: 진행 중이면 이어서 하기, 끝났으면(STOP으로 actual_minutes 저장) 결과 보기 */}
        {artwork.work_category === 'MOCK_EXAM' &&
          (artwork.actual_minutes ? (
            <Button
              variant="soft"
              size="compact"
              onClick={() => navigate(`/artworks/${artwork.id}/exam/result`)}
            >
              시험 결과 보기
            </Button>
          ) : (
            <Button size="compact" onClick={() => navigate(`/artworks/${artwork.id}/exam`)}>
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

        <ArtworkConditions artwork={artwork} options={options} />
        <ReferenceCompare key={artwork.updated_at} artwork={artwork} />

        <StageStepper stages={stages} />

        {renderTimeline ? (
          renderTimeline({ artworkId: artwork.id, sections })
        ) : (
          <div className={styles.stageList}>
            {sections.map((section) => (
              <div key={section.key} className={styles.stageList}>
                {section.node}
              </div>
            ))}
          </div>
        )}
        <PhotoViewer
          artworkId={artwork.id}
          photo={viewer?.photo}
          alt={viewer?.alt}
          onClose={closeViewer}
        />
        {actionError && <p className={styles.error}>{actionError}</p>}

        {completed ? (
          <>
            <Button
              variant="soft"
              size="compact"
              onClick={() => setStatus(reopenArtwork)}
              disabled={statusBusy}
            >
              {statusBusy ? '준비하는 중…' : '작업 다시 시작!'}
            </Button>
            <p className={styles.hint}>
              완성한 작품은 사진을 바꿀 수 없어요. 녹음과 첨삭은 계속 남길 수 있어요.
            </p>
          </>
        ) : (
          <>
            <Button
              size="compact"
              onClick={() => setStatus(completeArtwork)}
              disabled={!finalPhoto || statusBusy}
            >
              {statusBusy ? '저장하는 중…' : '작품 완성!'}
            </Button>
            {!finalPhoto && (
              <p className={styles.hint}>
                마지막 단계({stages.at(-1)?.label}) 사진을 올리면 작품을 완성할 수 있어요.
              </p>
            )}
          </>
        )}
        {/* 보조 동작: 작은 테두리 알약, 한 줄 */}
        <div className={styles.secondaryActions}>
          <button
            type="button"
            className={styles.pillButton}
            onClick={() => navigate(`/artworks/${artwork.id}/edit`)}
          >
            <PencilLine size={16} aria-hidden />
            수정
          </button>
          {hasAnyPhoto && (
            <button
              type="button"
              className={styles.pillButton}
              onClick={() => navigate(`/community/write?artwork=${artwork.id}`)}
            >
              <Share2 size={16} aria-hidden />
              커뮤니티에 공유
            </button>
          )}
        </div>
        <button
          type="button"
          className={styles.deleteArtwork}
          onClick={handleDeleteArtwork}
          disabled={deleting}
        >
          <Trash2 size={14} aria-hidden />
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

/** v1.1 시험 조건·표현 의도 (값이 있는 것만). 주제·시간은 위에서 이미 보여 줌 */
function ArtworkConditions({ artwork, options }) {
  const methodLabel = (code) =>
    labelOf(
      options?.expression_methods?.length ? options.expression_methods : EXPRESSION_METHODS,
      code,
    )
  const shown = new Set(['실기 주제', '시험 시간'])
  const rows = artworkConditions(artwork, methodLabel).filter(
    (r) => !shown.has(r.label) && !(r.label === '메모' && !artwork.topic),
  )
  if (!rows.length) return null
  return (
    <Card>
      <dl className={refStyles.conditions}>
        {rows.map((r) => (
          <div key={r.label} style={{ display: 'contents' }}>
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

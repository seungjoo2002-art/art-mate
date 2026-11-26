import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, Sparkles, Trash2, X } from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, SegmentedTabs } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { usePolling } from '../../../hooks/usePolling'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getArtwork, getPhotoUrl } from '../api'
import ArtworkPhoto from '../components/ArtworkPhoto'
import PhotoCarousel from '../components/PhotoCarousel'
import viewerStyles from '../components/PhotoViewer.module.css'
import { stagePhotos, stagesWithPhotos } from '../stages'
import { deleteRevision, getStageRevisions } from './api'
import CompareSlider from './CompareSlider'
import {
  defaultRevision,
  groupImprovements,
  hasImage,
  isPending,
  ordinal,
  pageTitle,
  revisionsByPhoto,
  statusText,
} from './revisionView'
import styles from './AiRevisionsPage.module.css'

const POLL_MS = 4000
const MODES = [
  { key: 'original', label: '원본' },
  { key: 'compare', label: '비교' },
  { key: 'revision', label: 'AI 수정작' },
]

/**
 * 단계별 AI 수정본 화면 (v1.3): /artworks/:artworkId/stages/:stageId/ai-revisions?photo=&revision=
 * - 위: 원본 사진별 가로 슬라이드 (수정본이 없는 사진도 포함), 사진 n / N, 이전·다음, 점 표시
 * - 원본 | 비교 | AI 수정작 (기본 비교, 고른 사진에 수정본이 없으면 원본)
 * - 아래: 수정에 요청한 개선사항(생성 당시 스냅샷), 생성 시각, 수정 이력(버전 선택·삭제)
 * 조회·비교만 하므로 이미지 수정 AI를 다시 부르지 않는다. AI 수정본은 학생 작품 사진이 아니다.
 */
export default function AiRevisionsPage() {
  const { artworkId, stageId } = useParams()
  const [params, setParams] = useSearchParams()
  const loadArtwork = useCallback(() => getArtwork(artworkId), [artworkId])
  const { data: artwork, error, reload } = useAsync(loadArtwork)
  const loadStage = useCallback(() => getStageRevisions(artworkId, stageId), [artworkId, stageId])
  const { data: revisions, error: stageError, reload: loadRevisions } = useAsync(loadStage)
  const [actionError, setActionError] = useState('')
  const [mode, setMode] = useState('compare')
  const [chosen, setChosen] = useState({}) // photoId → revisionId
  const [locked, setLocked] = useState(false)
  const [viewer, setViewer] = useState(null) // { src, alt, caption } | { photo }
  const [historyOpen, setHistoryOpen] = useState(false)
  const [busyId, setBusyId] = useState(null)

  const list = revisions?.revisions ?? []
  usePolling(list.some(isPending), POLL_MS, loadRevisions, [revisions])

  if (error) {
    return (
      <FullScreenStatus title="작품을 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!artwork) return <FullScreenStatus />

  const stage = stagesWithPhotos(artwork).find((s) => s.id === stageId)
  if (!stage) {
    return (
      <FullScreenStatus title="단계를 찾을 수 없어요">
        <Button onClick={() => window.history.back()}>돌아가기</Button>
      </FullScreenStatus>
    )
  }
  const photos = stagePhotos(artwork, stage.id)
  const byPhoto = revisionsByPhoto(photos, list)
  const found = photos.findIndex((p) => p.id === params.get('photo'))
  const index = found >= 0 ? found : 0
  const photo = photos[index] ?? null
  const groups = photo ? byPhoto.get(photo.id) : { current: [], previous: [] }
  const history = [...groups.current, ...groups.previous]

  const selectedFor = (p) => {
    const g = byPhoto.get(p.id)
    const all = [...g.current, ...g.previous]
    const wanted = chosen[p.id] ?? (p.id === photo?.id ? params.get('revision') : null)
    return all.find((r) => r.id === wanted) ?? defaultRevision(g.current)
  }
  const selected = photo ? selectedFor(photo) : null
  const effective = (revision) => (hasImage(revision) ? mode : 'original')
  const newest = groups.current[0]
  const newerPending = newest && isPending(newest) && newest.id !== selected?.id

  const selectPhoto = (i) => {
    const next = new URLSearchParams(params)
    next.set('photo', photos[i].id)
    next.delete('revision')
    setParams(next, { replace: true })
  }

  function choose(revision, nextMode) {
    setChosen((c) => ({ ...c, [photo.id]: revision.id }))
    if (nextMode) setMode(nextMode)
    setHistoryOpen(false)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function remove(revision) {
    if (!window.confirm(`v${revision.version} AI 수정본을 삭제할까요? 원본 사진은 그대로예요.`))
      return
    setBusyId(revision.id)
    try {
      await deleteRevision(revision.id)
      setChosen((c) => {
        const next = { ...c }
        if (next[photo.id] === revision.id) delete next[photo.id]
        return next
      })
      setActionError('')
      loadRevisions()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  const feedbackPath = `/artworks/${artwork.id}/feedback?stage=${stage.id}${
    photo ? `&photo=${photo.id}` : ''
  }`

  const renderSlide = (p) => {
    const revision = selectedFor(p)
    const shown = effective(revision)
    const sourceId = revision?.photo_id ?? p.id
    if (shown === 'compare') {
      return (
        <ComparePair
          key={`${p.id}-${revision.id}`}
          artworkId={artwork.id}
          photoId={sourceId}
          url={sourceId === p.id ? p.url : null}
          ratio={p.width && p.height && sourceId === p.id ? p.width / p.height : null}
          revision={revision}
          onDraggingChange={setLocked}
          onExpired={loadRevisions}
        />
      )
    }
    if (shown === 'revision') {
      return (
        <span className={styles.slideInner}>
          <img
            src={revision.url}
            alt={`AI 수정 예시 v${revision.version}`}
            className={styles.image}
            draggable={false}
            onError={loadRevisions}
          />
          <span className={`${styles.badge} ${styles.badgeAi}`}>
            <Sparkles size={12} aria-hidden /> AI 수정 예시
          </span>
        </span>
      )
    }
    return (
      <span className={styles.slideInner}>
        <ArtworkPhoto
          key={sourceId}
          artworkId={artwork.id}
          photoId={sourceId}
          url={sourceId === p.id ? p.url : undefined}
          alt={`${stage.label} 원본 사진`}
          className={styles.image}
          loading="eager"
        />
        <span className={styles.badge}>원본</span>
      </span>
    )
  }

  function openViewer(p) {
    const revision = selectedFor(p)
    if (effective(revision) === 'revision') {
      setViewer({ src: revision.url, alt: 'AI 수정 예시', caption: 'AI 수정 예시' })
    } else {
      const sourceId = revision?.photo_id ?? p.id
      setViewer({
        photoId: sourceId,
        url: sourceId === p.id ? p.url : undefined,
        caption: '원본 작품',
      })
    }
  }

  return (
    <>
      <TopBar title={pageTitle(stage.label)} belowHeader />
      <main className={styles.body}>
        <p className={styles.artwork}>{artwork.title}</p>
        {!photos.length ? (
          <div className={styles.empty}>
            <p>아직 이 단계 사진이 없어요.</p>
          </div>
        ) : (
          <section className={styles.viewerBlock} aria-label={`${stage.label} AI 수정본`}>
            <div className={styles.pager}>
              {photos.length > 1 && (
                <button
                  type="button"
                  className={styles.pageButton}
                  onClick={() => selectPhoto(index - 1)}
                  disabled={index === 0}
                  aria-label="이전 원본 사진"
                >
                  <ChevronLeft size={20} aria-hidden />
                </button>
              )}
              <span className={styles.pageText} aria-live="polite">
                사진 {index + 1} / {photos.length}
              </span>
              {photos.length > 1 && (
                <button
                  type="button"
                  className={styles.pageButton}
                  onClick={() => selectPhoto(index + 1)}
                  disabled={index === photos.length - 1}
                  aria-label="다음 원본 사진"
                >
                  <ChevronRight size={20} aria-hidden />
                </button>
              )}
            </div>
            <SegmentedTabs
              tabs={MODES}
              value={effective(selected)}
              onChange={setMode}
              label="보기 방식"
            />
            <PhotoCarousel
              artworkId={artwork.id}
              photos={photos}
              index={index}
              onIndexChange={selectPhoto}
              alt={`${stage.label} 사진`}
              renderSlide={renderSlide}
              canOpen={(p) => effective(selectedFor(p)) !== 'compare'}
              onOpen={openViewer}
              locked={locked}
              className={styles.carousel}
            />
          </section>
        )}

        {(stageError || actionError) && (
          <p className={styles.error}>
            {stageError
              ? `AI 수정본을 불러오지 못했어요. ${toErrorMessage(stageError)} `
              : actionError}{' '}
            <button type="button" className={styles.textButton} onClick={loadRevisions}>
              다시 시도
            </button>
          </p>
        )}

        {photo && revisions && (
          <>
            {newerPending && <StatusCard revision={newest} />}
            {!hasImage(selected) ? (
              <section className={styles.emptyCard}>
                {selected && (isPending(selected) || statusText(selected)) ? (
                  <StatusCard revision={selected} inline />
                ) : (
                  <p className={styles.emptyTitle}>아직 생성된 AI 수정본이 없어요.</p>
                )}
                <p className={styles.caption}>
                  단계별 피드백 화면에서 이 사진의 개선사항을 골라 ‘피드백 반영 수정하기’를 눌러
                  보세요.
                </p>
                <Link to={feedbackPath} className={styles.feedbackLink}>
                  이 사진 피드백 화면으로 가기
                </Link>
              </section>
            ) : (
              <>
                <p className={styles.meta}>
                  <span className={styles.aiTag}>
                    <Sparkles size={12} aria-hidden /> AI 수정 예시 v{selected.version}
                  </span>
                  <span>{formatUploadedAt(selected.finished_at ?? selected.created_at)} 생성</span>
                </p>
                {selected.photo_id !== photo.id && (
                  <p className={styles.previousNote}>
                    교체 전 사진으로 만든 수정본이에요. 비교 화면도 그때의 원본과 비교해요.
                  </p>
                )}
                <Improvements revision={selected} />
              </>
            )}

            {history.length > 0 && (
              <section className={styles.history}>
                <button
                  type="button"
                  className={styles.historyToggle}
                  onClick={() => setHistoryOpen((o) => !o)}
                  aria-expanded={historyOpen}
                >
                  수정 이력 보기 ({history.length}개)
                  <ChevronRight
                    size={16}
                    aria-hidden
                    className={historyOpen ? styles.chevronOpen : ''}
                  />
                </button>
                {historyOpen && (
                  <ol className={styles.historyList}>
                    {history.map((revision) => (
                      <HistoryItem
                        key={revision.id}
                        revision={revision}
                        previous={revision.photo_id !== photo.id}
                        current={revision.id === selected?.id}
                        busy={busyId === revision.id}
                        onCompare={() => choose(revision, 'compare')}
                        onSelect={() => choose(revision)}
                        onDelete={() => remove(revision)}
                      />
                    ))}
                  </ol>
                )}
              </section>
            )}
          </>
        )}

        <p className={styles.footer}>
          AI 수정본은 강사 피드백을 바탕으로 생성한 학습용 참고 이미지예요. 실제 작품을 직접 수정할
          때 활용해 보세요.
        </p>
      </main>
      {viewer && (
        <ZoomViewer artworkId={artwork.id} viewer={viewer} onClose={() => setViewer(null)} />
      )}
    </>
  )
}

/** 비교: 원본 주소(만료되면 새로 받음) + AI 수정작 주소 */
function ComparePair({ artworkId, photoId, url, ratio, revision, onDraggingChange, onExpired }) {
  const [src, setSrc] = useState(url)
  const [retried, setRetried] = useState(false)

  useEffect(() => {
    if (url) return undefined
    let cancelled = false
    getPhotoUrl(artworkId, photoId).then(
      (signed) => !cancelled && setSrc(signed.url),
      () => {},
    )
    return () => {
      cancelled = true
    }
  }, [artworkId, photoId, url])

  // 원본 Signed URL 만료: 한 번만 새로 받음
  async function refreshOriginal() {
    if (retried) return
    setRetried(true)
    try {
      setSrc((await getPhotoUrl(artworkId, photoId)).url)
    } catch {
      // 그대로
    }
  }

  if (!src) return <span className={styles.placeholder} aria-hidden />
  return (
    <span className={styles.slideInner}>
      <CompareSlider
        originalSrc={src}
        revisionSrc={revision.url}
        ratio={ratio}
        onDraggingChange={onDraggingChange}
        onOriginalError={refreshOriginal}
        onRevisionError={onExpired}
      />
    </span>
  )
}

function StatusCard({ revision, inline = false }) {
  const status = statusText(revision)
  if (!status) return null
  const pending = isPending(revision)
  return (
    <div
      className={`${styles.status} ${inline ? styles.statusInline : ''} ${pending ? '' : styles.statusFail}`}
      aria-live="polite"
    >
      <strong>{pending ? `새 수정본 v${revision.version}: ${status.title}` : status.title}</strong>
      <span>{status.sub}</span>
    </div>
  )
}

/** 수정에 요청한 개선사항 (생성 당시 스냅샷, 카테고리별) */
function Improvements({ revision }) {
  const groups = groupImprovements(revision.improvements)
  return (
    <section className={styles.improvements} aria-label="수정에 요청한 개선사항">
      <h2 className={styles.heading}>수정에 요청한 개선사항</h2>
      <p className={styles.caption}>
        AI에게 아래 내용을 반영하도록 요청했어요. 실제로 모두 정확히 반영됐는지는 원본과 비교해
        확인해 주세요.
      </p>
      <ol className={styles.groupList}>
        {groups.map((group, i) => (
          <li key={group.category} className={styles.group}>
            <h3 className={styles.groupTitle}>
              <span className={styles.number}>{ordinal(i)}.</span> {group.label}
            </h3>
            <ul className={styles.items}>
              {group.items.map((item) => (
                <li key={item.key}>
                  <span className={styles.kind}>{item.kind_label}</span> {item.text}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  )
}

function HistoryItem({ revision, previous, current, busy, onCompare, onSelect, onDelete }) {
  const image = hasImage(revision)
  const status = statusText(revision)
  return (
    <li className={`${styles.historyItem} ${current ? styles.historyCurrent : ''}`}>
      <button
        type="button"
        className={styles.thumb}
        onClick={onSelect}
        disabled={!image}
        aria-label={`v${revision.version} 보기`}
      >
        {image ? (
          <img src={revision.url} alt="" className={styles.thumbImage} />
        ) : (
          <Sparkles size={18} aria-hidden />
        )}
      </button>
      <div className={styles.historyBody}>
        <p className={styles.historyTitle}>
          v{revision.version} · {formatUploadedAt(revision.finished_at ?? revision.created_at)}
          {current && <span className={styles.currentTag}>보는 중</span>}
        </p>
        {previous && <p className={styles.historySub}>교체 전 사진의 수정본</p>}
        <p className={styles.historySub}>
          개선사항 {revision.improvements.length}개 · {revision.improvements[0]?.text}
        </p>
        <p className={styles.historySub}>
          {revision.model_name}
          {!image && status ? ` · ${status.title}` : ''}
        </p>
        <div className={styles.historyActions}>
          {image && (
            <button type="button" className={styles.textButton} onClick={onCompare}>
              원본과 비교하기
            </button>
          )}
          {!isPending(revision) && (
            <button
              type="button"
              className={styles.deleteButton}
              onClick={onDelete}
              disabled={busy}
              aria-label={`v${revision.version} 수정본 삭제`}
            >
              <Trash2 size={14} aria-hidden />
              {busy ? '삭제하는 중…' : '삭제'}
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

/** 크게 보기 (원본·AI 수정작). 원본과 혼동되지 않게 아래에 구분 문구 */
function ZoomViewer({ artworkId, viewer, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = overflow
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])
  return createPortal(
    <div
      className={viewerStyles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-label={viewer.caption}
      onClick={onClose}
    >
      <button
        type="button"
        className={viewerStyles.close}
        onClick={onClose}
        aria-label="닫기"
        autoFocus
      >
        <X size={24} aria-hidden />
      </button>
      {viewer.src ? (
        <img src={viewer.src} alt={viewer.alt} className={viewerStyles.image} />
      ) : (
        <ArtworkPhoto
          artworkId={artworkId}
          photoId={viewer.photoId}
          url={viewer.url}
          alt="원본 작품"
          className={viewerStyles.image}
          loading="eager"
        />
      )}
      <p className={viewerStyles.caption}>{viewer.caption}</p>
    </div>,
    document.body,
  )
}

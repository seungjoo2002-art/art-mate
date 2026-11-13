import { useState } from 'react'
import { Image as ImageIcon } from 'lucide-react'
import PhotoChooser from '../../../components/photo/PhotoChooser'
import { Button } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import { saveFeedbackImageRefs } from '../api'
import { stagePhotos } from '../stages'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './FeedbackRefs.module.css'

const STATUS_TEXT = {
  CONFIRMED: '이 사진을 보고 받은 피드백',
  SUGGESTED: '피드백 당시 최신 사진을 제안했어요. 맞는지 확인해 주세요',
  NONE: '기준 사진 없음',
}

/**
 * 피드백 기준 이미지 (v0.9.8): 이 피드백이 어떤 작품 사진을 보고 작성됐는지.
 * 제안(SUGGESTED)은 확인 전까지 학습 데이터로 쓰지 않으므로 확인·변경 버튼을 보여 준다.
 * 저장된 연결은 이후 사진이 추가돼도 바뀌지 않는다 (바꾸려면 여기서 직접 변경).
 * feedback: { type, id, image_refs }
 */
export default function FeedbackRefs({ artwork, feedback, stages, onChanged }) {
  const refs = feedback.image_refs ?? { status: 'NONE', photos: [] }
  const [editing, setEditing] = useState(false)
  const [selected, setSelected] = useState(() => refs.photos.map((p) => p.photo_id))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const photoById = Object.fromEntries(artwork.photos.map((p) => [p.id, p]))
  const stageName = (id) => stages.find((s) => s.id === id)?.label

  async function save(photoIds) {
    setBusy(true)
    setError('')
    try {
      await saveFeedbackImageRefs(artwork.id, feedback, photoIds, true)
      setEditing(false)
      onChanged()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const groups = stages
    .filter((s) => s.id)
    .map((s) => ({
      key: s.id,
      label: s.label,
      photos: stagePhotos(artwork, s.id).map((p) => ({ id: p.id, url: p.url })),
    }))

  return (
    <div className={`${styles.box} ${refs.status === 'SUGGESTED' ? styles.suggested : ''}`}>
      <span className={styles.head}>
        <ImageIcon size={14} aria-hidden />
        기준 사진 · {STATUS_TEXT[refs.status] ?? STATUS_TEXT.NONE}
      </span>
      {refs.photos.length > 0 && !editing && (
        <ul className={styles.thumbs}>
          {refs.photos.map((ref) => (
            <li key={ref.photo_id} className={styles.thumb}>
              {ref.photo_status === 'ACTIVE' && photoById[ref.photo_id] ? (
                <ArtworkPhoto
                  artworkId={artwork.id}
                  photoId={ref.photo_id}
                  url={photoById[ref.photo_id].url}
                  className={styles.image}
                />
              ) : (
                <span className={`${styles.image} ${styles.gone}`}>삭제된 사진</span>
              )}
              {stageName(ref.stage_id) && (
                <span className={styles.caption}>{stageName(ref.stage_id)}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <>
          <PhotoChooser
            groups={groups}
            selected={selected}
            onToggle={toggle}
            renderImage={(photo, className) => (
              <ArtworkPhoto
                artworkId={artwork.id}
                photoId={photo.id}
                url={photo.url}
                className={className}
              />
            )}
          />
          <div className={styles.actions}>
            <Button variant="soft" onClick={() => setEditing(false)} disabled={busy}>
              취소
            </Button>
            <Button onClick={() => save(selected)} disabled={busy}>
              {busy ? '저장하는 중…' : selected.length ? '이 사진으로 저장' : '사진 없이 받은 피드백'}
            </Button>
          </div>
        </>
      ) : (
        <div className={styles.links}>
          {refs.status === 'SUGGESTED' && (
            <button
              type="button"
              onClick={() => save(refs.photos.map((p) => p.photo_id))}
              disabled={busy}
            >
              맞아요
            </button>
          )}
          <button type="button" onClick={() => setEditing(true)} disabled={busy}>
            {refs.status === 'NONE' && !refs.photos.length ? '기준 사진 고르기' : '변경'}
          </button>
        </div>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}

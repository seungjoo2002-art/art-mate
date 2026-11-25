import { useState } from 'react'
import { Check, Image as ImageIcon } from 'lucide-react'
import PhotoChooser from '../../../components/photo/PhotoChooser'
import { toErrorMessage } from '../../../utils/errorMessages'
import { saveFeedbackImageRefs } from '../api'
import { stagePhotos } from '../stages'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './FeedbackRefs.module.css'

// 상태별 한 줄: 제목 + 작은 설명
const STATUS_TEXT = {
  CONFIRMED: { title: '이 사진을 보고 받은 피드백', sub: '' },
  SUGGESTED: {
    title: '이 사진 보고 받은 피드백 맞나요?',
    sub: '자동으로 골라 둔 사진이에요',
  },
  NONE: {
    title: '어떤 사진을 보고 받은 피드백인가요?',
    sub: '고르면 첨삭과 사진을 같이 볼 수 있어요',
  },
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
  // 고르기는 지금 있는 사진에서만 (교체·삭제된 사진은 다시 고를 수 없음)
  const [selected, setSelected] = useState(() =>
    refs.photos.filter((p) => p.photo_status === 'ACTIVE').map((p) => p.photo_id),
  )
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

  const text = STATUS_TEXT[refs.status] ?? STATUS_TEXT.NONE
  // 교체·삭제된 사진이 섞인 제안은 그대로 확인할 수 없음 (서버는 지금 있는 사진만 받음) → 다시 고르기
  const suggested =
    refs.status === 'SUGGESTED' && refs.photos.every((p) => p.photo_status === 'ACTIVE')

  return (
    <div className={`${styles.box} ${styles[refs.status] ?? ''}`}>
      {!editing && (
        <div className={styles.row}>
          {refs.photos.length > 0 ? (
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
                  ) : ref.replaced ? (
                    // 교체된 사진: 피드백 받을 때 본 교체 전 사진을 그대로 (서버가 파일을 남겨 둠)
                    <ArtworkPhoto
                      artworkId={artwork.id}
                      photoId={ref.photo_id}
                      className={styles.image}
                      fallback={<span className={`${styles.image} ${styles.gone}`}>삭제됨</span>}
                    />
                  ) : (
                    <span className={`${styles.image} ${styles.gone}`}>삭제됨</span>
                  )}
                  {(ref.replaced || stageName(ref.stage_id)) && (
                    <span className={styles.caption}>
                      {ref.replaced ? '교체 전 사진' : stageName(ref.stage_id)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <span className={styles.placeholder} aria-hidden>
              <ImageIcon size={18} />
            </span>
          )}
          <span className={styles.text}>
            <span className={styles.title}>
              {refs.status === 'CONFIRMED' && <Check size={13} aria-hidden />}
              {text.title}
            </span>
            {text.sub && <span className={styles.sub}>{text.sub}</span>}
          </span>
        </div>
      )}

      {editing ? (
        <>
          <span className={styles.title}>피드백 받을 때 본 사진을 골라 주세요</span>
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
            <button
              type="button"
              className={styles.textButton}
              onClick={() => setEditing(false)}
              disabled={busy}
            >
              취소
            </button>
            <button
              type="button"
              className={styles.pill}
              onClick={() => save(selected)}
              disabled={busy}
            >
              {busy ? '저장하는 중…' : selected.length ? '이 사진으로' : '사진 없이 받았어요'}
            </button>
          </div>
        </>
      ) : (
        <div className={styles.actions}>
          {suggested ? (
            <>
              <button
                type="button"
                className={styles.textButton}
                onClick={() => setEditing(true)}
                disabled={busy}
              >
                다른 사진이에요
              </button>
              <button
                type="button"
                className={styles.pill}
                onClick={() => save(refs.photos.map((p) => p.photo_id))}
                disabled={busy}
              >
                {busy ? '저장하는 중…' : '맞아요'}
              </button>
            </>
          ) : (
            <button
              type="button"
              className={refs.status === 'NONE' ? styles.pillSoft : styles.textButton}
              onClick={() => setEditing(true)}
              disabled={busy}
            >
              {refs.status === 'NONE' && !refs.photos.length ? '사진 고르기' : '바꾸기'}
            </button>
          )}
        </div>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}

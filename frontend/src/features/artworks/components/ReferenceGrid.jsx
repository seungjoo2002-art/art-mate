import { useRef } from 'react'
import { ImagePlus, RefreshCw, Trash2, X } from 'lucide-react'
import styles from './ReferenceGrid.module.css'

const ACCEPT = 'image/jpeg,image/png,image/webp'

/**
 * v1.1 원본 제시물 사진 격자 (작품 등록·수정·상세 공통, 모바일 우선 2~3열).
 * uploaded: 서버에 올라간 사진 [{ id, url }], queue: 올리기 전·중·실패 파일 (useReferenceUploads)
 * 파일 고르기는 accept=이미지 → 휴대폰에서는 카메라·앨범을 함께 고를 수 있다
 */
export default function ReferenceGrid({
  uploaded = [],
  queue = [],
  max,
  disabled = false,
  onAdd,
  onDelete,
  onReplace,
  onRetry,
  onRemoveQueued,
}) {
  const addRef = useRef(null)
  const replaceRef = useRef(null)
  const replaceTarget = useRef(null)
  const used = uploaded.length + queue.filter((q) => !q.replacesId).length
  const canAdd = onAdd && used < max

  return (
    <div className={styles.wrap}>
      <ul className={styles.grid} aria-label="원본 제시물 사진">
        {uploaded.map((photo, i) => (
          <li key={photo.id} className={styles.tile}>
            {photo.url ? (
              <img src={photo.url} alt={`원본 제시물 ${i + 1}`} className={styles.image} />
            ) : (
              <span className={styles.placeholder}>원본 {i + 1}</span>
            )}
            <span className={styles.badge}>{i + 1}</span>
            <div className={styles.actions}>
              {onReplace && (
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={`원본 ${i + 1} 교체`}
                  disabled={disabled}
                  onClick={() => {
                    replaceTarget.current = photo.id
                    replaceRef.current?.click()
                  }}
                >
                  <RefreshCw size={16} />
                </button>
              )}
              {onDelete && (
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={`원본 ${i + 1} 삭제`}
                  disabled={disabled}
                  onClick={() => onDelete(photo)}
                >
                  <Trash2 size={16} />
                </button>
              )}
            </div>
          </li>
        ))}
        {queue.map((item) => (
          <li
            key={item.key}
            className={`${styles.tile} ${item.status === 'failed' ? styles.failed : ''}`}
          >
            <img src={item.preview} alt="올릴 원본 사진" className={styles.image} />
            <span className={styles.state} role="status">
              {item.status === 'uploading'
                ? '올리는 중…'
                : item.status === 'failed'
                  ? '실패'
                  : item.replacesId
                    ? '교체 대기'
                    : '저장하면 올려요'}
            </span>
            <div className={styles.actions}>
              {item.status === 'failed' && onRetry && (
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label="다시 시도"
                  onClick={() => onRetry(item)}
                >
                  <RefreshCw size={16} />
                </button>
              )}
              {item.status !== 'uploading' && onRemoveQueued && (
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label="빼기"
                  onClick={() => onRemoveQueued(item)}
                >
                  <X size={16} />
                </button>
              )}
            </div>
          </li>
        ))}
        {canAdd && (
          <li className={styles.tile}>
            <button
              type="button"
              className={styles.add}
              disabled={disabled}
              onClick={() => addRef.current?.click()}
            >
              <ImagePlus size={24} aria-hidden />
              <span>사진 추가</span>
            </button>
          </li>
        )}
      </ul>
      {queue
        .filter((q) => q.status === 'failed')
        .map((q) => (
          <p key={q.key} className={styles.error}>
            {q.file.name}: {q.error}
          </p>
        ))}
      <p className={styles.hint}>
        {used}/{max}장 · JPG·PNG·WEBP, 10MB 이하. 원본은 작품의 모든 단계에서 함께 참고해요.
      </p>
      <input
        ref={addRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const files = [...e.target.files]
          e.target.value = ''
          if (files.length) onAdd(files)
        }}
      />
      <input
        ref={replaceRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          const [file] = e.target.files
          e.target.value = ''
          if (file && replaceTarget.current) onReplace(replaceTarget.current, file)
        }}
      />
    </div>
  )
}

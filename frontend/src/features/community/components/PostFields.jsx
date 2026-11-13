import { Chip } from '../../../components/ui'
import styles from '../pages/PostWritePage.module.css'

const STAGE_LABELS = { SKETCH: '스케치', PROGRESS: '중간 작업', FINAL: '완성' }

/** 공유할 작품 사진 고르기 (스케치·중간·완성 중 아무 사진) */
export function PhotoPicker({ photos, value, onChange }) {
  return (
    <div className={styles.photos} role="radiogroup" aria-label="공유할 사진">
      {photos.map((p) => (
        <button
          key={p.id}
          type="button"
          role="radio"
          aria-checked={value === p.id}
          className={`${styles.photo} ${value === p.id ? styles.photoSelected : ''}`}
          onClick={() => onChange(p.id)}
        >
          {p.url ? <img src={p.url} alt="" /> : <span aria-hidden />}
          <span className={styles.photoLabel}>{STAGE_LABELS[p.stage] ?? p.stage}</span>
        </button>
      ))}
    </div>
  )
}

/** 작성자 표시: 닉네임 / 익명 */
export function AuthorDisplay({ value, onChange }) {
  return (
    <div className={styles.authorDisplay}>
      <span className={styles.label}>작성자 표시</span>
      <div className={styles.chips} role="radiogroup" aria-label="작성자 표시">
        <Chip
          role="radio"
          aria-checked={value === 'NAME'}
          selected={value === 'NAME'}
          onClick={() => onChange('NAME')}
        >
          내 닉네임으로
        </Chip>
        <Chip
          role="radio"
          aria-checked={value === 'ANONYMOUS'}
          selected={value === 'ANONYMOUS'}
          onClick={() => onChange('ANONYMOUS')}
        >
          익명으로
        </Chip>
      </div>
    </div>
  )
}

import { Check } from 'lucide-react'
import styles from './PhotoChooser.module.css'

/**
 * 작품 사진 여러 장 고르기 (피드백 기준 이미지, v0.9.8).
 * groups: [{ key, label, photos: [{ id, url, caption }] }] — 단계별로 묶어 보여 줌
 * selected: 고른 사진 id 배열 (순서 = 고른 순서), onToggle(id)
 * renderImage(photo): 이미지 그리기를 바꿀 때 (만료된 Signed URL 재발급 등). 없으면 <img>
 */
export default function PhotoChooser({ groups, selected, onToggle, max = 10, renderImage }) {
  const full = selected.length >= max
  return (
    <div className={styles.chooser}>
      {groups
        .filter((g) => g.photos.length > 0)
        .map((group) => (
          <section key={group.key} className={styles.group} aria-label={group.label}>
            <span className={styles.groupLabel}>{group.label}</span>
            <ul className={styles.grid}>
              {group.photos.map((photo) => {
                const order = selected.indexOf(photo.id)
                const on = order >= 0
                return (
                  <li key={photo.id}>
                    <button
                      type="button"
                      className={`${styles.item} ${on ? styles.on : ''}`}
                      aria-pressed={on}
                      onClick={() => onToggle(photo.id)}
                      disabled={!on && full}
                    >
                      {renderImage ? (
                        renderImage(photo, styles.image)
                      ) : photo.url ? (
                        <img src={photo.url} alt="" className={styles.image} />
                      ) : (
                        <span className={styles.image} aria-hidden />
                      )}
                      {on && (
                        <span className={styles.check} aria-hidden>
                          {selected.length > 1 ? order + 1 : <Check size={14} strokeWidth={3} />}
                        </span>
                      )}
                      {photo.caption && <span className={styles.caption}>{photo.caption}</span>}
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
    </div>
  )
}

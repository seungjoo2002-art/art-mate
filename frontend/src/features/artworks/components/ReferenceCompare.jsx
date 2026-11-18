import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { listReferencePhotos } from '../api'
import { latestArtworkPhoto } from '../referencePhotos'
import styles from './ReferenceGrid.module.css'

/**
 * v1.1 작품 상세: 원본 제시물과 내 작품을 나란히 (휴대폰에서도 두 칸, 가로 스크롤 없음).
 * 원본이 여러 장이면 아래 썸네일로 고른다. 작품 사진은 대표 사진 → 없으면 가장 최근 사진.
 * AI 분석 결과는 v1.2부터 (여기서는 사진만 보여 줌)
 */
export default function ReferenceCompare({ artwork }) {
  const load = useCallback(() => listReferencePhotos(artwork.id), [artwork.id])
  const { data, error } = useAsync(load)
  const [selected, setSelected] = useState(0)
  if (error || !data) return null

  const refs = data.items
  if (!refs.length) {
    return (
      <p className={styles.hint}>
        원본 제시물 사진을 올리면 내 작품과 나란히 비교할 수 있어요.{' '}
        <Link to={`/artworks/${artwork.id}/edit`}>원본 사진 추가</Link>
      </p>
    )
  }
  const ref = refs[Math.min(selected, refs.length - 1)]
  const mine = latestArtworkPhoto(artwork)

  return (
    <section className={styles.compare} aria-label="원본과 내 작품 비교">
      <div className={styles.pair}>
        <figure className={styles.figure}>
          <div className={styles.frame}>
            {ref.url && <img src={ref.url} alt="원본 제시물" className={styles.contain} />}
          </div>
          <figcaption>
            원본 제시물
            {refs.length > 1 ? ` ${selected + 1}/${refs.length}` : ''}
          </figcaption>
        </figure>
        <figure className={styles.figure}>
          <div className={styles.frame}>
            {mine ? (
              <img src={mine.url} alt="내 작품" className={styles.contain} />
            ) : (
              <span className={styles.placeholder}>작품 사진을 올리면 여기에 보여요</span>
            )}
          </div>
          <figcaption>내 작품</figcaption>
        </figure>
      </div>
      {refs.length > 1 && (
        <div className={styles.thumbs}>
          {refs.map((r, i) => (
            <button
              key={r.id}
              type="button"
              className={`${styles.thumb} ${i === selected ? styles.thumbOn : ''}`}
              aria-label={`원본 ${i + 1} 보기`}
              aria-pressed={i === selected}
              onClick={() => setSelected(i)}
            >
              {r.url && <img src={r.url} alt="" className={styles.image} />}
            </button>
          ))}
        </div>
      )}
    </section>
  )
}

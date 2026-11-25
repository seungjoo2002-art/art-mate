import { ChevronRight, MessageSquareText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { countByStage } from '../feedbackGroups'
import { useArtworkFeedback } from '../useArtworkFeedback'
import AddFeedbackButtons from './AddFeedbackButtons'
import styles from './FeedbackTimeline.module.css'

/**
 * 작품 상세의 단계별 묶음 (아카이브 상세):
 * 단계마다 [단계 머리·사진 슬라이드(section.node) → 녹음·글 첨삭 등록 아이콘 → '단계 피드백 보기 (N개)'],
 * 맨 아래 '작품 전체 피드백'. 피드백 내용은 여기 늘어놓지 않고 피드백 보기 화면에서 본다.
 * sections: [{ key, stageId, title, node, photoId? }] — stageId가 없으면(예전 응답) 모든 피드백이 전체 피드백
 *   photoId: 지금 슬라이드에서 보는 사진 → 새 피드백의 기본 기준 사진
 * actions: 맨 아래 (작품 쪽에서 넘긴 버튼 등)
 */
export default function FeedbackTimeline({ artworkId, sections, actions = null }) {
  const { items, error, reload } = useArtworkFeedback(artworkId)
  const stageIds = new Set(sections.map((s) => s.stageId).filter(Boolean))
  const counts = items ? countByStage(items, stageIds) : null
  const staged = stageIds.size > 0

  const viewLink = (label, stageId, photoId) => {
    const params = new URLSearchParams()
    if (stageId) params.set('stage', stageId)
    if (photoId) params.set('photo', photoId)
    const query = params.toString()
    const count = counts?.get(stageId ?? null) ?? 0
    return (
      <Link
        to={`/artworks/${artworkId}/feedback${query ? `?${query}` : ''}`}
        className={styles.viewButton}
      >
        <MessageSquareText size={16} aria-hidden />
        <span className={styles.viewLabel}>
          {label} 피드백 보기{counts ? ` (${count}개)` : ''}
        </span>
        <ChevronRight size={16} aria-hidden className={styles.viewChevron} />
      </Link>
    )
  }

  return (
    <section className={styles.section}>
      {sections.map((section) => (
        <section key={section.key} className={styles.stage} aria-label={section.title}>
          {section.node}
          {section.stageId && (
            <div className={styles.stageFoot}>
              <AddFeedbackButtons
                artworkId={artworkId}
                stageId={section.stageId}
                photoId={section.photoId}
                compact
              />
              {viewLink(`${section.title} 단계`, section.stageId, section.photoId)}
            </div>
          )}
        </section>
      ))}

      <section className={styles.stage} aria-label="작품 전체 피드백">
        <h2 className={styles.heading}>{staged ? '작품 전체 피드백' : '피드백'}</h2>
        {staged && (
          <p className={styles.caption}>특정 단계가 아닌 작품 전체에 대한 피드백이에요.</p>
        )}
        {error && (
          <p className={styles.error}>
            피드백을 불러오지 못했어요.{' '}
            <button type="button" className={styles.retry} onClick={reload}>
              다시 시도
            </button>
          </p>
        )}
        <div className={styles.stageFoot}>
          <AddFeedbackButtons artworkId={artworkId} />
          {viewLink(staged ? '작품 전체' : '전체', null)}
        </div>
        {actions}
      </section>
    </section>
  )
}

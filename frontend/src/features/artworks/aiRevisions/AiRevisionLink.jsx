import { useEffect, useState } from 'react'
import { ChevronRight, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getRevisionFeature, getRevisionSummaryShared } from './api'
import styles from './AiRevisionLink.module.css'

/**
 * 아카이브 상세: 단계 '피드백 보기' 바로 아래 '✨ AI 수정본 보기 (N개)' (v1.3).
 * 수정본 이미지는 여기 펼치지 않고 단계별 AI 수정본 화면으로 이동한다.
 * 기능이 꺼져 있고(운영자 확인 전) 이 단계에 수정본도 없으면 버튼을 보여 주지 않는다.
 */
export default function AiRevisionLink({ artworkId, stageId, stageLabel, photoId }) {
  const [state, setState] = useState(null) // { enabled, count, inProgress }

  useEffect(() => {
    let cancelled = false
    Promise.all([getRevisionFeature(), getRevisionSummaryShared(artworkId).catch(() => null)]).then(
      ([feature, summary]) => {
        if (cancelled) return
        const stage = summary?.stages.find((s) => s.stage_id === stageId)
        setState({
          enabled: feature === 'ENABLED',
          count: stage?.count ?? 0,
          inProgress: stage?.in_progress ?? 0,
        })
      },
    )
    return () => {
      cancelled = true
    }
  }, [artworkId, stageId])

  if (!state || (!state.enabled && state.count === 0 && state.inProgress === 0)) return null
  const params = photoId ? `?photo=${photoId}` : ''
  return (
    <Link
      to={`/artworks/${artworkId}/stages/${stageId}/ai-revisions${params}`}
      className={styles.link}
      aria-label={`${stageLabel} AI 수정본 보기 ${state.count}개`}
    >
      <Sparkles size={16} aria-hidden className={styles.icon} />
      <span className={styles.label}>
        AI 수정본 보기 ({state.count}개){state.inProgress > 0 && ' · 만드는 중'}
      </span>
      <ChevronRight size={16} aria-hidden className={styles.chevron} />
    </Link>
  )
}

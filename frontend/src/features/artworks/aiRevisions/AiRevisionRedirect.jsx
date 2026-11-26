import { useCallback } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getRevision } from './api'

/** 알림 'AI 수정본이 준비됐어요' → 그 수정본을 연 단계별 AI 수정본 화면 (/ai-revisions/:id) */
export default function AiRevisionRedirect() {
  const { revisionId } = useParams()
  const load = useCallback(() => getRevision(revisionId), [revisionId])
  const { data: revision, error, reload } = useAsync(load)

  if (error) {
    return (
      <FullScreenStatus title="AI 수정본을 찾을 수 없어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!revision) return <FullScreenStatus />
  // 교체 전 사진의 수정본이면 지금 그 자리의 사진에서 이력으로 보여 줌
  const photoId = revision.source_photo.current_photo_id ?? revision.photo_id
  return (
    <Navigate
      replace
      to={`/artworks/${revision.artwork_id}/stages/${revision.stage_id}/ai-revisions?photo=${photoId}&revision=${revision.id}`}
    />
  )
}

import { useCallback } from 'react'
import { useAsync } from '../../hooks/useAsync'
import { listRecordings } from './api'
import { listNotes } from './notesApi'

/**
 * 작품의 피드백 전부 (녹음 + 글 첨삭)를 한 모양으로.
 * items: [{ key, type: 'RECORDING' | 'NOTE', id, stageId, time, imageRefs, recording | note }]
 * (둘 다 불러오기 전이면 null). 두 API 모두 페이지 객체가 아니라 배열을 그대로 돌려줌
 */
export function useArtworkFeedback(artworkId) {
  const loadRecordings = useCallback(() => listRecordings(artworkId), [artworkId])
  const recordings = useAsync(loadRecordings)
  const loadNotes = useCallback(() => listNotes(artworkId), [artworkId])
  const notes = useAsync(loadNotes)

  const items =
    recordings.data && notes.data
      ? [
          ...recordings.data.map((recording) => ({
            key: recording.id,
            type: 'RECORDING',
            id: recording.id,
            stageId: recording.stage_id ?? null,
            time: recording.recorded_at ?? recording.uploaded_at ?? recording.created_at,
            imageRefs: recording.image_refs,
            recording,
          })),
          ...notes.data.map((note) => ({
            key: note.id,
            type: 'NOTE',
            id: note.id,
            stageId: note.stage_id ?? null,
            time: note.created_at,
            imageRefs: note.image_refs,
            note,
          })),
        ]
      : null

  return {
    items,
    error: recordings.error ?? notes.error ?? null,
    reloadRecordings: recordings.reload,
    reloadNotes: notes.reload,
    reload: () => {
      recordings.reload()
      notes.reload()
    },
  }
}

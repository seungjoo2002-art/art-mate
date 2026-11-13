import { useCallback, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Checkbox, Chip, Input, Textarea } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getAiConsent } from '../aiApi'
import StagePicker from '../components/StagePicker'
import { createNote, getNote, updateNote } from '../notesApi'
import styles from './NoteFormPage.module.css'

const DEFAULT_SOURCES = [
  { code: 'INSTRUCTOR', label: '강사 첨삭' },
  { code: 'SELF_NOTE', label: '자기 메모' },
  { code: 'PEER', label: '다른 학생 의견' },
]

const today = () => new Date().toLocaleDateString('sv-SE') // YYYY-MM-DD (로컬 날짜)

/** 글로 첨삭 남기기 (/artworks/:artworkId/notes/new) · 수정 (/feedback-notes/:noteId/edit) */
export default function NoteFormPage() {
  const { artworkId, noteId } = useParams()
  const load = useCallback(() => (noteId ? getNote(noteId) : Promise.resolve(null)), [noteId])
  const { data: note, error, loading, reload } = useAsync(load)

  if (error) {
    return (
      <FullScreenStatus title="첨삭을 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (loading) return <FullScreenStatus />

  return <NoteForm key={note?.id ?? 'new'} artworkId={note?.artwork_id ?? artworkId} note={note} />
}

function NoteForm({ artworkId, note }) {
  const navigate = useNavigate()
  const location = useLocation()
  const options = useOptions()
  const sources = options?.feedback_sources ?? DEFAULT_SOURCES
  const [source, setSource] = useState(note?.source ?? 'INSTRUCTOR')
  const [body, setBody] = useState(note?.body ?? '')
  const [feedbackDate, setFeedbackDate] = useState(note?.feedback_date ?? today())
  const [withAi, setWithAi] = useState(!note)
  // v0.9.7 단계 피드백: 작품 화면의 단계에서 들어오면 ?stage=단계 id. '' = 작품 전체
  const [params] = useSearchParams()
  const [stageId, setStageId] = useState(note ? (note.stage_id ?? '') : (params.get('stage') ?? ''))
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const artworkPath = `/artworks/${artworkId}`

  async function handleSubmit(e) {
    e.preventDefault()
    if (!body.trim()) {
      setFormError('첨삭 내용을 입력해 주세요.')
      return
    }
    setSaving(true)
    setFormError('')
    try {
      if (note) {
        await updateNote(note.id, {
          version: note.version,
          source,
          body: body.trim(),
          feedbackDate,
          // 단계는 바꾼 경우에만 보냄 (원문이 아니라 AI 정리는 그대로)
          ...(stageId !== (note.stage_id ?? '') ? { stageId: stageId || null } : {}),
        })
        navigate(artworkPath, { replace: true })
        return
      }
      // AI 동의가 없으면 저장만 되고 요약은 요청되지 않음 → 동의 화면으로 안내
      const consent = withAi ? await getAiConsent() : null
      await createNote(artworkId, {
        source,
        body: body.trim(),
        feedbackDate,
        stageId: stageId || undefined,
        requestSummary: withAi && consent.is_valid,
      })
      if (withAi && !consent.is_valid) {
        navigate('/ai-consent', { replace: true, state: { from: artworkPath } })
        return
      }
      navigate(artworkPath, { replace: true })
    } catch (err) {
      setFormError(toErrorMessage(err))
      setSaving(false)
    }
  }

  return (
    <>
      <TopBar title={note ? '첨삭 수정' : '글로 첨삭 남기기'} belowHeader />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        <div className={styles.field}>
          <span className={styles.label}>누구의 첨삭인가요?</span>
          <div className={styles.chips} role="radiogroup" aria-label="첨삭 출처">
            {sources.map((s) => (
              <Chip
                key={s.code}
                role="radio"
                aria-checked={source === s.code}
                selected={source === s.code}
                onClick={() => setSource(s.code)}
              >
                {s.label}
              </Chip>
            ))}
          </div>
          {source !== 'INSTRUCTOR' && (
            <p className={styles.hint}>
              자기 메모·다른 학생 의견은 참고용으로 보관하고, 반복 약점 분석에는 넣지 않아요.
            </p>
          )}
        </div>

        <StagePicker artworkId={artworkId} value={stageId} onChange={setStageId} />

        <Textarea
          label="첨삭 내용"
          rows={8}
          maxLength={5000}
          placeholder={
            '예) 구도는 안정적이다. 오른쪽 컵의 명암이 약하다.\n시간 안에 배경을 끝내지 못했다.'
          }
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <p className={styles.counter}>{body.length} / 5000</p>

        <Input
          label="첨삭 받은 날"
          type="date"
          max={today()}
          value={feedbackDate}
          onChange={(e) => setFeedbackDate(e.target.value)}
        />

        {!note && (
          <Checkbox checked={withAi} onChange={setWithAi}>
            저장하고 AI로 정리하기
          </Checkbox>
        )}
        {note?.feedback_status && note.feedback_status !== 'APPROVED' && (
          <p className={styles.hint}>
            내용을 바꾸면 기존 AI 정리 초안은 사라져요. 저장 후 다시 정리해 주세요.
          </p>
        )}

        {formError && <p className={styles.error}>{formError}</p>}
        <Button type="submit" disabled={saving}>
          {saving ? '저장하는 중…' : '저장하기'}
        </Button>
        <Button
          variant="soft"
          onClick={() => navigate(location.state?.from ?? artworkPath)}
          disabled={saving}
        >
          취소
        </Button>
      </form>
    </>
  )
}

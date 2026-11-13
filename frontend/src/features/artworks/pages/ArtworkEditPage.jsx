import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Input, Select } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getArtwork, listStages, replaceStages, updateArtwork } from '../api'
import StageEditor from '../components/StageEditor'
import { stageListError, toStageSpecs } from '../stages'
import styles from './ArtworkPage.module.css'

/** 작품 정보 수정 (/artworks/:artworkId/edit) */
export default function ArtworkEditPage() {
  const { artworkId } = useParams()
  const load = useCallback(
    () => Promise.all([getArtwork(artworkId), listStages(artworkId)]),
    [artworkId],
  )
  const { data, error, reload } = useAsync(load)

  if (error) {
    return (
      <FullScreenStatus title="작품을 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!data) return <FullScreenStatus />
  return <ArtworkEditForm artwork={data[0]} stagePlan={data[1]} />
}

const toRow = (s) => ({ key: s.id, id: s.id, name: s.name, minutes: s.target_minutes ?? 30 })
const sameStages = (a, b) =>
  JSON.stringify(a.map((s) => [s.id, s.name.trim(), s.minutes])) ===
  JSON.stringify(b.map((s) => [s.id, s.name.trim(), s.minutes]))

const toNumber = (v) => (v === '' ? null : Number(v))

function ArtworkEditForm({ artwork, stagePlan }) {
  const navigate = useNavigate()
  const options = useOptions()
  const [form, setForm] = useState({
    title: artwork.title,
    practical_type: artwork.practical_type ?? '',
    work_category: artwork.work_category ?? '',
    topic: artwork.topic ?? '',
    work_method: artwork.work_method ?? '',
    actual_minutes: artwork.actual_minutes ?? '',
    time_limit_minutes: artwork.time_limit_minutes ?? '',
  })
  const initialStages = stagePlan.filter((s) => !s.archived).map(toRow)
  const [stages, setStages] = useState(initialStages)
  const archived = stagePlan.filter((s) => s.archived && !stages.some((row) => row.id === s.id))
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const set = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.title.trim()) {
      setFormError('작품명을 입력해 주세요.')
      return
    }
    const minutes = ['actual_minutes', 'time_limit_minutes'].map((k) => toNumber(form[k]))
    if (minutes.some((m) => m !== null && (!Number.isInteger(m) || m < 1 || m > 1440))) {
      setFormError('시간은 1분에서 1440분(24시간) 사이로 입력해 주세요.')
      return
    }
    const exam = form.work_category === 'MOCK_EXAM'
    const stageError = stageListError(stages, { withMinutes: exam })
    if (stageError) {
      setFormError(stageError)
      return
    }
    const removed = initialStages.filter((s) => !stages.some((row) => row.id === s.id))
    if (
      removed.length &&
      !window.confirm(
        `${removed.map((s) => s.name).join(', ')} 단계를 뺄까요? 사진이나 피드백이 있는 단계는 지우지 않고 숨겨 두고, 나중에 다시 추가할 수 있어요.`,
      )
    ) {
      return
    }
    setSaving(true)
    setFormError('')
    try {
      await updateArtwork(artwork.id, {
        title: form.title.trim(),
        practical_type: form.practical_type || null,
        work_category: form.work_category || null,
        topic: form.topic.trim() || null,
        work_method: form.work_method.trim() || null,
        actual_minutes: minutes[0],
        time_limit_minutes: minutes[1],
      })
      // 단계는 바뀐 경우에만 (시험 작품은 단계 목표 시간의 합이 제한 시간이 됨)
      if (!sameStages(stages, initialStages)) {
        await replaceStages(artwork.id, toStageSpecs(stages, { withMinutes: exam }))
      }
      navigate(`/artworks/${artwork.id}`, { replace: true })
    } catch (err) {
      setFormError(toErrorMessage(err))
      setSaving(false)
    }
  }

  const withEmpty = (list, label) => [{ code: '', label }, ...(list ?? [])]

  return (
    <>
      <TopBar title="작품 정보 수정" belowHeader plain />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        <Input label="작품명" maxLength={200} value={form.title} onChange={set('title')} />
        <Select
          label="실기 유형"
          options={withEmpty(options?.practical_types, '미분류')}
          value={form.practical_type}
          onChange={set('practical_type')}
        />
        <Select
          label="작품 분류"
          options={withEmpty(options?.work_categories, '미분류')}
          value={form.work_category}
          onChange={set('work_category')}
        />
        <Input
          label="주제 또는 소재 (선택)"
          maxLength={200}
          placeholder="예: 유리컵과 운동화"
          value={form.topic}
          onChange={set('topic')}
        />
        <Input
          label="작업 방식 (선택)"
          maxLength={100}
          placeholder="예: 4B 연필, 수채"
          value={form.work_method}
          onChange={set('work_method')}
        />
        <Input
          label="실제 소요 시간 (분, 선택)"
          type="number"
          inputMode="numeric"
          min={1}
          max={1440}
          placeholder="예: 240"
          value={form.actual_minutes}
          onChange={set('actual_minutes')}
        />
        <p className={styles.caption}>
          타이머 없이 그린 작품은 직접 입력하세요. 성장 리포트의 학습 시간 통계에 쓰여요.
        </p>
        <Input
          label="제한 시간 (분, 선택)"
          type="number"
          inputMode="numeric"
          min={1}
          max={1440}
          placeholder="예: 300"
          value={form.time_limit_minutes}
          onChange={set('time_limit_minutes')}
        />
        <StageEditor
          stages={stages}
          onChange={setStages}
          withMinutes={form.work_category === 'MOCK_EXAM'}
          note="이름·순서를 바꿔도 사진과 피드백은 그대로 그 단계에 남아요. 사진이나 피드백이 있는 단계를 빼면 지우지 않고 숨겨요."
        />
        {archived.length > 0 && (
          <div className={styles.field}>
            <span className={styles.fieldLabel}>숨긴 단계 (사진·피드백 보관 중)</span>
            <div className={styles.chips}>
              {archived.map((s) => (
                <Button
                  key={s.id}
                  type="button"
                  variant="soft"
                  onClick={() => setStages((prev) => [...prev, toRow(s)])}
                >
                  {s.name} 다시 추가
                </Button>
              ))}
            </div>
          </div>
        )}
        {formError && <p className={styles.error}>{formError}</p>}
        <Button type="submit" disabled={saving}>
          {saving ? '저장하는 중…' : '저장하기'}
        </Button>
      </form>
    </>
  )
}

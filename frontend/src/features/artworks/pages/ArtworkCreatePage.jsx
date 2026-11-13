import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Input, Select } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createArtwork, deleteArtwork, putExamPlan } from '../api'
import StageEditor from '../components/StageEditor'
import {
  DEFAULT_STAGE_TARGETS,
  EXAM_CODES,
  MAX_EXAM_STAGES,
  loadExamDefaults,
  rowsToPlan,
  saveExamDefaults,
  totalMinutes,
} from '../exam'
import { DEFAULT_STAGE_NAMES, newStageRow, stageListError, toStageSpecs } from '../stages'
import styles from './ArtworkPage.module.css'

/** 작품명을 비우면 쓰는 임시 제목. 예: "기초디자인 · 11월 11일" */
function fallbackTitle(typeLabel, exam) {
  const today = new Date()
  const date = `${today.getMonth() + 1}월 ${today.getDate()}일`
  return `${typeLabel || (exam ? '실기시험' : '작품')} · ${date}`
}

/**
 * /artworks/new (새 작품 기록) · /artworks/new?mode=exam (실기시험: 모의시험 + 제한 시간)
 * v0.9.7: 제작 단계를 학생이 정함 (기본 스케치 · 채색 · 완성, 1~10개).
 * 시험 모드: 단계 이름(최대 4개)과 단계별 목표 시간. 목표 기본값은 계정에서 불러오고(VER.2),
 * 진행은 서버 시험 계획(/exam/plan)으로 → 시험 단계 i = 작품 단계 i
 */
export default function ArtworkCreatePage() {
  const navigate = useNavigate()
  const { profile } = useAuth()
  const options = useOptions()
  const [params] = useSearchParams()
  const recommendationId = params.get('recommendation')
  const exam = params.get('mode') === 'exam'
  // 시험 목표 기본값은 계정에서 불러오고, 이 화면에서 바꾸면 그 값을 씀 (시작할 때 다음 시험 기본값으로 저장)
  const loadDefaults = useCallback(
    () => (exam ? loadExamDefaults() : Promise.resolve(null)),
    [exam],
  )
  const { data: defaults } = useAsync(loadDefaults)
  const initialRows = useMemo(
    () =>
      exam
        ? (defaults ?? DEFAULT_STAGE_TARGETS)
            .slice(0, MAX_EXAM_STAGES)
            .map((t) => newStageRow(t.label, { minutes: t.minutes }))
        : DEFAULT_STAGE_NAMES.map((name) => newStageRow(name)),
    [exam, defaults],
  )
  const [editedStages, setStages] = useState(null)
  const stages = editedStages ?? initialRows
  const [title, setTitle] = useState('')
  const [practicalType, setPracticalType] = useState(profile.practical_type ?? '')
  const [topic, setTopic] = useState('')
  const [examMaterials, setExamMaterials] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    const stageError =
      stageListError(stages, { withMinutes: exam }) ||
      (exam && stages.length > MAX_EXAM_STAGES
        ? `시험 단계는 ${MAX_EXAM_STAGES}개까지 만들 수 있어요.`
        : '')
    if (stageError) {
      setFormError(stageError)
      return
    }
    setSubmitting(true)
    setFormError('')
    const typeLabel =
      practicalType && options ? labelOf(options.practical_types, practicalType) : ''
    try {
      // 다음 시험 기본값 (단계 코드·목표 시간만 계정에 저장, 실패해도 시험은 시작)
      if (exam && editedStages) {
        await saveExamDefaults(
          stages.map((s, i) => ({ key: EXAM_CODES[i], minutes: s.minutes })),
        ).catch(() => {})
      }
      const artwork = await createArtwork({
        title: title.trim() || fallbackTitle(typeLabel, exam),
        topic: topic.trim(),
        examMaterials: examMaterials.trim() || undefined,
        recommendationId,
        practicalType: practicalType || undefined,
        workCategory: exam ? 'MOCK_EXAM' : undefined,
        timeLimitMinutes: exam ? totalMinutes(stages) : undefined,
        stages: toStageSpecs(stages, { withMinutes: exam }),
      })
      if (exam) {
        // 단계 계획은 타이머 START 전에 저장해야 첫 단계가 함께 시작됨 (실패하면 작품을 지우고 다시)
        try {
          await putExamPlan(artwork.id, rowsToPlan(stages))
        } catch (err) {
          await deleteArtwork(artwork.id).catch(() => {})
          throw err
        }
        navigate(`/artworks/${artwork.id}/exam`, { replace: true })
      } else {
        navigate(`/artworks/${artwork.id}`, { replace: true })
      }
    } catch (error) {
      setFormError(toErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <>
      <TopBar title={exam ? '실기시험 준비' : '새 작품 기록'} belowHeader plain />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        <p className={styles.lead}>
          {exam
            ? '시험 조건을 확인하고 시작하면 단계별 기록 화면으로 이동합니다.'
            : '작품 정보를 입력하고 바로 단계별 기록을 시작하세요.'}
        </p>
        {recommendationId && <Card variant="soft">맞춤 연습 과제를 수행한 작품으로 기록돼요.</Card>}

        <Input
          label="작품명"
          placeholder="예: 유리컵과 사과 연습"
          maxLength={200}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Select
          label="실기 유형"
          placeholder="실기 유형 선택"
          options={options?.practical_types}
          value={practicalType}
          onChange={(e) => setPracticalType(e.target.value)}
        />
        <Input
          label="주제 또는 소재 (선택)"
          placeholder="예: 유리컵과 운동화"
          maxLength={200}
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
        />
        <Input
          label="제시물 (선택)"
          placeholder="예: 유리컵, 사과 2개, 흰 천"
          maxLength={500}
          value={examMaterials}
          onChange={(e) => setExamMaterials(e.target.value)}
        />

        <StageEditor
          stages={stages}
          onChange={setStages}
          withMinutes={exam}
          maxStages={exam ? MAX_EXAM_STAGES : undefined}
          note="단계마다 사진과 피드백, 피드백을 반영한 수정 사진을 따로 기록할 수 있어요. 단계는 나중에 작품 정보 수정에서 바꿀 수 있어요."
        />

        {formError && <p className={styles.error}>{formError}</p>}
        <div className={styles.submit}>
          <Button type="submit" withArrow disabled={submitting}>
            {submitting ? '만드는 중…' : exam ? '시험 시작하기' : '작품 기록 시작하기'}
          </Button>
          <p className={styles.caption}>
            작품명을 입력하지 않으면 자동으로 임시 제목이 지정됩니다. 시작 버튼을 누르면 단계별 기록
            화면으로 이동합니다.
          </p>
        </div>
      </form>
    </>
  )
}

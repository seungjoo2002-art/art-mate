import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import TopBar from '../../../components/layout/TopBar'
import { PencilLine } from 'lucide-react'
import mascotCat from '../../../assets/mascot/mascot-cat.webp'
import { Button, Card, Input } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createArtwork, deleteArtwork, putExamPlan } from '../api'
import ExamIntentFields from '../components/ExamIntentFields'
import ReferenceGrid from '../components/ReferenceGrid'
import StageEditor from '../components/StageEditor'
import StagePath from '../components/StagePath'
import {
  DEFAULT_STAGE_TARGETS,
  EXAM_CODES,
  MAX_EXAM_STAGES,
  loadExamDefaults,
  rowsToPlan,
  saveExamDefaults,
  totalMinutes,
} from '../exam'
import {
  acceptFiles,
  DEFAULT_MAX_REFERENCE_PHOTOS,
  examIntentFromArtwork,
  examIntentPayload,
} from '../referencePhotos'
import { DEFAULT_STAGE_NAMES, newStageRow, stageListError, toStageSpecs } from '../stages'
import { tabColor, tabLabel } from '../sectionTabs'
import tabStyles from '../SectionTabs.module.css'
import { useReferenceUploads } from '../useReferenceUploads'
import createStyles from './ArtworkCreate.module.css'
import styles from './ArtworkPage.module.css'

/** 실기 유형 칩의 물감 점 색 (코드에 없는 유형은 주황) */
const TYPE_COLORS = {
  BASIC_DESIGN: '#f2933a',
  THINKING_SHIFT: '#7c6ee6',
  IDEA_EXPRESSION: '#e0607e',
  DRAWING: '#555555',
  WATERCOLOR: '#3fa7d6',
  OTHER: '#9aa33f',
}

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
  const [editingStages, setEditingStages] = useState(false)
  const stages = editedStages ?? initialRows
  const [title, setTitle] = useState('')
  const [practicalType, setPracticalType] = useState(profile.practical_type ?? '')
  const [topic, setTopic] = useState('')
  const [examMaterials, setExamMaterials] = useState('')
  const [details, setDetails] = useState(() => examIntentFromArtwork())
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // v1.1 원본 제시물: 작품을 만든 뒤 올린다. 일부 실패하면 만든 작품에 남은 파일만 다시 올림 (입력 보존)
  const references = useReferenceUploads()
  const [refMessages, setRefMessages] = useState([])
  const [created, setCreated] = useState(null)

  const typeLabelOf = (code) => (code && options ? labelOf(options.practical_types, code) : '')

  function addReferences(files) {
    const used = references.queue.length
    const { accepted, rejected } = acceptFiles(files, DEFAULT_MAX_REFERENCE_PHOTOS - used)
    setRefMessages(rejected.map((r) => `${r.name}: ${r.message}`))
    if (accepted.length) references.add(accepted)
  }

  function goToArtwork(artwork) {
    navigate(exam ? `/artworks/${artwork.id}/exam` : `/artworks/${artwork.id}`, { replace: true })
  }

  /** 원본 사진 올리기 → 모두 성공하면 이동, 실패가 있으면 이 화면에서 다시 시도·건너뛰기 */
  async function uploadReferencesThenGo(artwork) {
    const failed = await references.uploadAll(artwork.id)
    if (failed) {
      setCreated(artwork)
      setFormError(
        `원본 사진 ${failed}장을 올리지 못했어요. 다시 시도하거나 건너뛰고 나중에 작품 수정에서 추가할 수 있어요.`,
      )
      setSubmitting(false)
      return
    }
    goToArtwork(artwork)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (created) {
      // 작품은 이미 만들어짐 → 실패한 원본 사진만 다시
      setSubmitting(true)
      setFormError('')
      await uploadReferencesThenGo(created)
      return
    }
    const limit = details.time_limit_minutes === '' ? null : Number(details.time_limit_minutes)
    if (!exam && limit !== null && (!Number.isInteger(limit) || limit < 1 || limit > 1440)) {
      setFormError('시험 시간은 1분에서 1440분(24시간) 사이로 입력해 주세요.')
      return
    }
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
    const typeLabel = typeLabelOf(practicalType)
    try {
      // 다음 시험 기본값 (단계 코드·목표 시간만 계정에 저장, 실패해도 시험은 시작)
      if (exam && editedStages) {
        await saveExamDefaults(
          stages.map((s, i) => ({ key: EXAM_CODES[i], minutes: s.minutes })),
        ).catch(() => {})
      }
      const extra = examIntentPayload(details)
      const artwork = await createArtwork({
        title: title.trim() || fallbackTitle(typeLabel, exam),
        topic: topic.trim(),
        examMaterials: examMaterials.trim() || undefined,
        recommendationId,
        practicalType: practicalType || undefined,
        workCategory: exam ? 'MOCK_EXAM' : undefined,
        timeLimitMinutes: exam ? totalMinutes(stages) : limit || undefined,
        stages: toStageSpecs(stages, { withMinutes: exam }),
        paperSize: extra.paper_size,
        examConditions: extra.exam_conditions,
        description: extra.description,
        expressionMethods: extra.expression_methods,
        expressionIntent: extra.expression_intent,
      })
      if (exam) {
        // 단계 계획은 타이머 START 전에 저장해야 첫 단계가 함께 시작됨 (실패하면 작품을 지우고 다시)
        try {
          await putExamPlan(artwork.id, rowsToPlan(stages))
        } catch (err) {
          await deleteArtwork(artwork.id).catch(() => {})
          throw err
        }
      }
      await uploadReferencesThenGo(artwork)
    } catch (error) {
      setFormError(toErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <>
      <TopBar title={exam ? '실기시험 준비' : '새 작품 기록'} belowHeader plain />
      <form className={`${styles.body} ${createStyles.form}`} onSubmit={handleSubmit} noValidate>
        {/* 고양이 인사 */}
        <div className={createStyles.hero}>
          <img className={createStyles.cat} src={mascotCat} alt="" />
          <p className={createStyles.bubble}>
            {exam ? '시험 조건부터 확인해요 ⏱️' : '오늘은 뭘 그려 볼까요? 🎨'}
          </p>
        </div>
        {recommendationId && <Card variant="soft">맞춤 연습 과제를 수행한 작품으로 기록돼요.</Card>}

        {/* 스케치북 표지 같은 제목 */}
        <div className={createStyles.titleField}>
          <input
            className={createStyles.title}
            aria-label="작품명"
            placeholder="작품 제목을 지어 주세요"
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        {/* 실기 유형: 물감 점 칩 (다시 누르면 선택 해제) */}
        <div className={createStyles.typeField}>
          <span className={createStyles.typeLabel} id="practical-type-label">
            실기 유형
          </span>
          <div className={createStyles.chips} role="radiogroup" aria-labelledby="practical-type-label">
            {(options?.practical_types ?? []).map((o) => (
              <button
                key={o.code}
                type="button"
                role="radio"
                aria-checked={practicalType === o.code}
                className={createStyles.chip}
                style={{ '--paint': TYPE_COLORS[o.code] ?? 'var(--color-primary)' }}
                onClick={() => setPracticalType(practicalType === o.code ? '' : o.code)}
              >
                <i className={createStyles.paint} aria-hidden />
                {o.label}
              </button>
            ))}
          </div>
        </div>

        {/* 원래 입력 순서 그대로, 칸마다 인덱스 탭 */}
        <section className={tabStyles.card} style={{ '--tab': tabColor(1) }}>
          <h2 className={tabStyles.tab}>{tabLabel(1, '주제 또는 소재')}</h2>
          <small className={tabStyles.cardMeta}>선택</small>
          <Input
            aria-label="주제 또는 소재"
            placeholder="예: 유리컵과 운동화"
            maxLength={200}
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
        </section>

        <section className={tabStyles.card} style={{ '--tab': tabColor(2) }}>
          <h2 className={tabStyles.tab}>{tabLabel(2, '제시물')}</h2>
          <small className={tabStyles.cardMeta}>선택</small>
          <Input
            aria-label="제시물"
            placeholder="예: 유리컵, 사과 2개, 흰 천"
            maxLength={500}
            value={examMaterials}
            onChange={(e) => setExamMaterials(e.target.value)}
          />
        </section>

        <section className={tabStyles.card} style={{ '--tab': tabColor(3) }}>
          <h2 className={tabStyles.tab}>{tabLabel(3, '원본 제시물 사진')}</h2>
          <small className={tabStyles.cardMeta}>
            선택 · 최대 {DEFAULT_MAX_REFERENCE_PHOTOS}장
          </small>
          <ReferenceGrid
            queue={references.queue}
            max={DEFAULT_MAX_REFERENCE_PHOTOS}
            disabled={submitting}
            onAdd={created ? undefined : addReferences}
            onRemoveQueued={(item) => references.remove(item.key)}
          />
          {refMessages.map((m) => (
            <p key={m} className={styles.error}>
              {m}
            </p>
          ))}
        </section>

        <ExamIntentFields
          value={details}
          onChange={setDetails}
          methodOptions={options?.expression_methods}
          showTime={!exam}
          startNumber={4}
        />

        <section className={tabStyles.card} style={{ '--tab': tabColor(6) }}>
          <h2 className={tabStyles.tab}>
            {tabLabel(6, exam ? '시험 단계와 목표 시간' : '제작 단계')}
          </h2>
          <small className={tabStyles.cardMeta}>{stages.length}단계</small>
          {/* 시험은 단계마다 시간을 정해야 해서 바로 편집 목록, 그 밖에는 물감 길 + 편집 열기 */}
          {!exam && <StagePath stages={stages} />}
          {exam || editingStages ? (
            <StageEditor
              embedded
              stages={stages}
              onChange={setStages}
              withMinutes={exam}
              maxStages={exam ? MAX_EXAM_STAGES : undefined}
              note="단계마다 사진과 피드백, 피드백을 반영한 수정 사진을 따로 기록할 수 있어요. 단계는 나중에 작품 정보 수정에서 바꿀 수 있어요."
            />
          ) : (
            <button
              type="button"
              className={createStyles.editStages}
              onClick={() => setEditingStages(true)}
            >
              <PencilLine size={14} aria-hidden />
              단계 바꾸기
            </button>
          )}
        </section>

        {formError && <p className={styles.error}>{formError}</p>}
        {/* 시작 버튼은 화면 아래에 늘 보이게 */}
        <div className={createStyles.bar}>
          <Button type="submit" size="compact" withArrow disabled={submitting}>
            {submitting
              ? references.queue.some((q) => q.status === 'uploading')
                ? '원본 사진 올리는 중…'
                : '만드는 중…'
              : created
                ? '원본 사진 다시 올리기'
                : exam
                  ? '시험 시작하기'
                  : '작품 기록 시작하기'}
          </Button>
          {created && !submitting && (
            <Button type="button" variant="soft" size="compact" onClick={() => goToArtwork(created)}>
              건너뛰고 계속하기
            </Button>
          )}
        </div>
      </form>
    </>
  )
}

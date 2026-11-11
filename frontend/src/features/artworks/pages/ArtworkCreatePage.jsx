import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Chip, Input, Select } from '../../../components/ui'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createArtwork } from '../api'
import { DEFAULT_EXAM_MINUTES, EXAM_LIMITS } from '../exam'
import styles from './ArtworkPage.module.css'

/** 작품명을 비우면 쓰는 임시 제목. 예: "기초디자인 · 11월 11일" */
function fallbackTitle(typeLabel, exam) {
  const today = new Date()
  const date = `${today.getMonth() + 1}월 ${today.getDate()}일`
  return `${typeLabel || (exam ? '실기시험' : '작품')} · ${date}`
}

/**
 * /artworks/new (새 작품 기록) · /artworks/new?mode=exam (실기시험: 모의시험 + 제한 시간)
 * 디자인의 실기 유형 "관리"와 "기록 중 단계 추가"는 백엔드가 없어 제외 (단계는 스케치·중간·완성 고정)
 */
export default function ArtworkCreatePage() {
  const navigate = useNavigate()
  const { profile } = useAuth()
  const options = useOptions()
  const [params] = useSearchParams()
  const recommendationId = params.get('recommendation')
  const exam = params.get('mode') === 'exam'
  const [timeLimit, setTimeLimit] = useState(DEFAULT_EXAM_MINUTES)
  const [title, setTitle] = useState('')
  const [practicalType, setPracticalType] = useState(profile.practical_type ?? '')
  const [topic, setTopic] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setFormError('')
    const typeLabel =
      practicalType && options ? labelOf(options.practical_types, practicalType) : ''
    try {
      const artwork = await createArtwork({
        title: title.trim() || fallbackTitle(typeLabel, exam),
        topic: topic.trim(),
        recommendationId,
        practicalType: practicalType || undefined,
        workCategory: exam ? 'MOCK_EXAM' : undefined,
        timeLimitMinutes: exam ? timeLimit : undefined,
      })
      navigate(`/artworks/${artwork.id}`, { replace: true })
    } catch (error) {
      setFormError(toErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <>
      <TopBar title={exam ? '실기시험 시작' : '새 작품 기록'} belowHeader plain />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        <p className={styles.lead}>
          {exam
            ? '제한 시간을 정하고 실전처럼 단계별 기록을 시작하세요.'
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

        {exam && (
          <div className={styles.field}>
            <span className={styles.fieldLabel}>제한 시간</span>
            <div className={styles.chips} role="radiogroup" aria-label="제한 시간">
              {EXAM_LIMITS.map((minutes) => (
                <Chip
                  key={minutes}
                  role="radio"
                  aria-checked={timeLimit === minutes}
                  selected={timeLimit === minutes}
                  onClick={() => setTimeLimit(minutes)}
                >
                  {minutes / 60}시간
                </Chip>
              ))}
            </div>
          </div>
        )}
        <p className={styles.caption}>
          스케치 · 중간 작업 · 완성 단계별로 사진과 피드백을 기록할 수 있어요.
        </p>

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

import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Chip, Input } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createArtwork } from '../api'
import { DEFAULT_EXAM_MINUTES, EXAM_LIMITS } from '../exam'
import styles from './ArtworkPage.module.css'

/** /artworks/new (자유 기록) · /artworks/new?mode=exam (실기시험: 모의시험 + 제한 시간) */
export default function ArtworkCreatePage() {
  const navigate = useNavigate()
  const { profile } = useAuth()
  const [params] = useSearchParams()
  const recommendationId = params.get('recommendation')
  const exam = params.get('mode') === 'exam'
  const [timeLimit, setTimeLimit] = useState(DEFAULT_EXAM_MINUTES)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!title.trim()) {
      setFormError('작품명을 입력해 주세요.')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      const artwork = await createArtwork({
        title: title.trim(),
        description: description.trim(),
        recommendationId,
        practicalType: profile.practical_type, // 내 주요 실기 유형으로 분류
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
      <TopBar title={exam ? '실기시험 시작' : '새 작품 기록'} belowHeader />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        {recommendationId && <Card variant="soft">맞춤 연습 과제를 수행한 작품으로 기록돼요.</Card>}
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
        <Input
          label="작품명"
          placeholder="정물 기초디자인 04"
          maxLength={200}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Input
          label="오늘의 주제 (선택)"
          placeholder="투명한 유리병과 붉은 사과"
          maxLength={1000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        {formError && <p className={styles.error}>{formError}</p>}
        <Button type="submit" withArrow disabled={submitting}>
          {submitting ? '만드는 중…' : exam ? '시험 시작하기' : '기록 시작하기'}
        </Button>
      </form>
    </>
  )
}

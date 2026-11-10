import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Input } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createArtwork } from '../api'
import styles from './ArtworkPage.module.css'

export default function ArtworkCreatePage() {
  const navigate = useNavigate()
  const recommendationId = useSearchParams()[0].get('recommendation')
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
      })
      navigate(`/artworks/${artwork.id}`, { replace: true })
    } catch (error) {
      setFormError(toErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <>
      <TopBar title="작품 제작 시작" belowHeader />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        {recommendationId && <Card variant="soft">맞춤 연습 과제를 수행한 작품으로 기록돼요.</Card>}
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
          {submitting ? '만드는 중…' : '작품 제작 시작'}
        </Button>
      </form>
    </>
  )
}

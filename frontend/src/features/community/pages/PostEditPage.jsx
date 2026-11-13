import { useCallback, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Chip, Input, Textarea } from '../../../components/ui'
import { api } from '../../../lib/api'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getPost, updatePost } from '../api'
import { AuthorDisplay, PhotoPicker } from '../components/PostFields'
import { CATEGORIES } from '../labels'
import styles from './PostWritePage.module.css'

// features끼리 import하지 않도록 작품 API를 직접 호출 (공유할 사진 다시 고르기용)
const getArtworkWithPhotos = (id) => api(`/artworks/${id}?include_urls=true`)

/** 내 게시물 수정 (/community/posts/:postId/edit) */
export default function PostEditPage() {
  const { postId } = useParams()
  const load = useCallback(() => getPost(postId), [postId])
  const { data: post, error } = useAsync(load)

  if (error) {
    return (
      <FullScreenStatus title="게시물을 불러오지 못했어요" description={toErrorMessage(error)} />
    )
  }
  if (!post) return <FullScreenStatus />
  if (!post.author.is_me) return <Navigate to={`/community/posts/${post.id}`} replace />
  return <EditForm post={post} />
}

function EditForm({ post }) {
  const navigate = useNavigate()
  const withArtwork = post.has_artwork
  const loadPhotos = useCallback(
    () =>
      withArtwork && post.artwork_id
        ? getArtworkWithPhotos(post.artwork_id)
        : Promise.resolve(null),
    [withArtwork, post.artwork_id],
  )
  const { data: artwork } = useAsync(loadPhotos)
  const [category, setCategory] = useState(post.category)
  const [title, setTitle] = useState(post.title)
  const [body, setBody] = useState(post.body ?? '')
  const [question, setQuestion] = useState(post.question ?? '')
  const [authorDisplay, setAuthorDisplay] = useState(
    post.author.is_anonymous ? 'ANONYMOUS' : 'NAME',
  )
  // 사진이 내려간 게시물(image=null)은 새로 골라야 함
  const [photoId, setPhotoId] = useState(post.image ? post.photo_id : null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  // 사진 없는 글은 작품 공유로 바꿀 수 없음 (서버 422)
  const categories = withArtwork ? CATEGORIES : CATEGORIES.filter((c) => c.code !== 'ARTWORK_SHARE')
  const photos = (artwork?.photos ?? []).filter((p) => p.status === 'ACTIVE')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!title.trim() || (!withArtwork && !body.trim())) {
      setFormError(withArtwork ? '제목을 입력해 주세요.' : '제목과 내용을 입력해 주세요.')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      await updatePost(post.id, {
        category,
        title: title.trim(),
        body: body.trim() || null,
        ...(withArtwork
          ? {
              question: question.trim() || null,
              ...(photoId && photoId !== post.photo_id ? { photo_id: photoId } : {}),
            }
          : { author_display: authorDisplay }),
      })
      navigate(`/community/posts/${post.id}`, { replace: true })
    } catch (err) {
      setFormError(toErrorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <>
      <TopBar title="게시물 수정" belowHeader plain />
      <form className={styles.body} onSubmit={handleSubmit} noValidate>
        <section className={styles.section}>
          <h2 className={styles.heading}>게시판</h2>
          <div className={styles.chips} role="radiogroup" aria-label="게시판 분류">
            {categories.map((c) => (
              <Chip
                key={c.code}
                role="radio"
                aria-checked={category === c.code}
                selected={category === c.code}
                onClick={() => setCategory(c.code)}
              >
                {c.label}
              </Chip>
            ))}
          </div>
        </section>

        {withArtwork && (
          <section className={styles.section}>
            <h2 className={styles.heading}>공유할 사진</h2>
            {!post.image && (
              <p className={styles.error}>공유한 사진이 내려갔어요. 다른 사진을 골라 주세요.</p>
            )}
            <PhotoPicker photos={photos} value={photoId} onChange={setPhotoId} />
            <p className={styles.hint}>
              원본 사진은 공개되지 않고, 공유용 이미지가 따로 만들어져요.
            </p>
          </section>
        )}

        <section className={styles.section}>
          {!withArtwork && <AuthorDisplay value={authorDisplay} onChange={setAuthorDisplay} />}
          <Input
            label="제목"
            maxLength={100}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <Textarea
            label={withArtwork ? '내용 (선택)' : '내용'}
            rows={5}
            maxLength={2000}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          {withArtwork && (
            <Textarea
              label="피드백 받고 싶은 점 (선택)"
              rows={3}
              maxLength={1000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          )}
          {formError && <p className={styles.error}>{formError}</p>}
          <Button type="submit" disabled={submitting || (withArtwork && !post.image && !photoId)}>
            {submitting ? '저장하는 중…' : '저장하기'}
          </Button>
        </section>
      </form>
    </>
  )
}

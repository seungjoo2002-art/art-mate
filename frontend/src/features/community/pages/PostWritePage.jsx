import { useCallback, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Checkbox, Chip, Input, Textarea } from '../../../components/ui'
import { api } from '../../../lib/api'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createPost, getSharing, grantCommunitySharing } from '../api'
import { AuthorDisplay, PhotoPicker } from '../components/PostFields'
import { CATEGORIES } from '../labels'
import styles from './PostWritePage.module.css'

// 공유 동의 고지 (docs/frontend-integration-v0.8.md §1, 법적 검토 전 초안)
const CONSENT_ITEMS = [
  ['공개되는 것', '고른 사진의 공유용 이미지, 게시물 제목·내용·질문, 실기 유형·작품 분류'],
  ['공개되지 않는 것', '원본 사진, 학원명, 연락처'],
  ['공개 범위', 'ART MATE를 쓰는 모든 사용자'],
  ['철회', '게시물을 삭제하면 공유도 함께 철회되고, 공개용 이미지도 바로 내려가요.'],
]

// features끼리 import하지 않도록 작품 API를 직접 호출
// VER.2 P0: 커뮤니티 공유는 사진 1장 이상이면 가능 (완성 사진 필수 아님)
const listShareableArtworks = () =>
  api('/artworks?limit=100').then((page) => page.items.filter((a) => a.photo_count > 0))
const getArtworkWithPhotos = (id) => api(`/artworks/${id}?include_urls=true`)

/**
 * 커뮤니티 글쓰기 (VER.2 P0)
 * 분류 선택 → (작품 공유는 필수, 나머지는 선택) 작품·공유할 사진 고르기 → (처음이면) 공유 동의 → 글
 */
export default function PostWritePage() {
  const [params, setParams] = useSearchParams()
  const artworkId = params.get('artwork')
  const [category, setCategory] = useState(artworkId ? 'ARTWORK_SHARE' : 'PRACTICE_QUESTION')
  const [attach, setAttach] = useState(Boolean(artworkId))
  const load = useCallback(() => listShareableArtworks(), [])
  const { data: artworks } = useAsync(load)
  const withArtwork = category === 'ARTWORK_SHARE' || attach
  const selected = withArtwork ? artworks?.find((a) => a.id === artworkId) : null

  const pickArtwork = (id) => setParams(id ? { artwork: id } : {}, { replace: true })

  return (
    <>
      <TopBar title="글쓰기" belowHeader plain />
      <main className={styles.body}>
        <section className={styles.section}>
          <h2 className={styles.heading}>게시판</h2>
          <div className={styles.chips} role="radiogroup" aria-label="게시판 분류">
            {CATEGORIES.map((c) => (
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

        <section className={styles.section}>
          <h2 className={styles.heading}>
            작품 사진 {category === 'ARTWORK_SHARE' ? '(필수)' : '(선택)'}
          </h2>
          {category !== 'ARTWORK_SHARE' && (
            <Checkbox checked={attach} onChange={setAttach}>
              내 작품 사진 함께 올리기
            </Checkbox>
          )}
          {withArtwork &&
            (!artworks ? null : artworks.length === 0 ? (
              <Card variant="soft" className={styles.notice}>
                사진이 있는 작품이 아직 없어요.
                <Link to="/practice" className={styles.link}>
                  작품 기록하러 가기
                </Link>
              </Card>
            ) : (
              <div className={styles.chips}>
                {artworks.map((a) => (
                  <Chip key={a.id} selected={a.id === artworkId} onClick={() => pickArtwork(a.id)}>
                    {a.title} · {formatMonthDay(a.work_date)}
                  </Chip>
                ))}
              </div>
            ))}
        </section>

        {withArtwork ? (
          selected && <ArtworkPostForm key={selected.id} artwork={selected} category={category} />
        ) : (
          <TextPostForm category={category} />
        )}
      </main>
    </>
  )
}

/** 작품 없이 쓰는 글: 본문 필수, 작성자 표시 선택 */
function TextPostForm({ category }) {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [authorDisplay, setAuthorDisplay] = useState('NAME')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!title.trim() || !body.trim()) {
      setFormError('제목과 내용을 입력해 주세요.')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      const post = await createPost({
        category,
        title: title.trim(),
        body: body.trim(),
        authorDisplay,
      })
      navigate(`/community/posts/${post.id}`, { replace: true })
    } catch (err) {
      setFormError(toErrorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <form className={styles.section} onSubmit={handleSubmit} noValidate>
      <AuthorDisplay value={authorDisplay} onChange={setAuthorDisplay} />
      <Input
        label="제목"
        maxLength={100}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <Textarea
        label="내용"
        rows={6}
        maxLength={2000}
        placeholder="궁금한 점이나 나누고 싶은 이야기를 적어 주세요."
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      {formError && <p className={styles.error}>{formError}</p>}
      <Button type="submit" disabled={submitting}>
        {submitting ? '올리는 중…' : '올리기'}
      </Button>
    </form>
  )
}

/** 작품 게시물: 공유할 사진 고르기 → (첫 공유면) 동의 → 제목·내용·질문 */
function ArtworkPostForm({ artwork, category }) {
  const navigate = useNavigate()
  const loadSharing = useCallback(() => getSharing(artwork.id), [artwork.id])
  const loadDetail = useCallback(() => getArtworkWithPhotos(artwork.id), [artwork.id])
  const { data: sharing, error } = useAsync(loadSharing)
  const { data: detail } = useAsync(loadDetail)
  const [photoId, setPhotoId] = useState(artwork.cover_photo_id)
  const [authorDisplay, setAuthorDisplay] = useState('ANONYMOUS')
  const [agreed, setAgreed] = useState(false)
  const [underFourteen, setUnderFourteen] = useState(false)
  const [guardianAgreed, setGuardianAgreed] = useState(false)
  const [title, setTitle] = useState(artwork.title)
  const [body, setBody] = useState('')
  const [question, setQuestion] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  if (error) return <p className={styles.error}>{toErrorMessage(error)}</p>
  if (!sharing) return null
  if (sharing.post_id) {
    return (
      <Card variant="soft" className={styles.notice}>
        이미 커뮤니티에 올린 작품이에요.
        <Link to={`/community/posts/${sharing.post_id}`} className={styles.link}>
          게시물 보기
        </Link>
      </Card>
    )
  }

  const needsConsent = !sharing.community
  const consentOk = !needsConsent || (agreed && (!underFourteen || guardianAgreed))
  const photos = detail?.photos ?? []

  async function handleSubmit(e) {
    e.preventDefault()
    if (!title.trim()) {
      setFormError('제목을 입력해 주세요.')
      return
    }
    if (!photoId) {
      setFormError('공유할 사진을 골라 주세요.')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      if (needsConsent) {
        await grantCommunitySharing(artwork.id, {
          authorDisplay,
          policyVersion: sharing.required_version,
          grantedBy: underFourteen ? 'GUARDIAN' : 'SELF',
        })
      }
      const post = await createPost({
        category,
        artworkId: artwork.id,
        photoId,
        title: title.trim(),
        body: body.trim(),
        question: question.trim(),
      })
      navigate(`/community/posts/${post.id}`, { replace: true })
    } catch (err) {
      setFormError(toErrorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <form className={styles.section} onSubmit={handleSubmit} noValidate>
      <h2 className={styles.heading}>공유할 사진</h2>
      <PhotoPicker photos={photos} value={photoId} onChange={setPhotoId} />
      <p className={styles.hint}>원본 사진은 공개되지 않고, 공유용 이미지가 따로 만들어져요.</p>

      {needsConsent && (
        <Card className={styles.consent}>
          <h2 className={styles.heading}>커뮤니티 공유 동의</h2>
          <dl className={styles.items}>
            {CONSENT_ITEMS.map(([term, detail]) => (
              <div key={term}>
                <dt>{term}</dt>
                <dd>{detail}</dd>
              </div>
            ))}
          </dl>
          <AuthorDisplay value={authorDisplay} onChange={setAuthorDisplay} />
          <Checkbox checked={agreed} onChange={setAgreed}>
            위 내용을 확인했고 이 작품을 커뮤니티에 공유하는 데 동의합니다.
          </Checkbox>
          <Checkbox checked={underFourteen} onChange={setUnderFourteen}>
            만 14세 미만이에요.
          </Checkbox>
          {underFourteen && (
            <Checkbox checked={guardianAgreed} onChange={setGuardianAgreed}>
              보호자(법정대리인)에게 알리고 동의를 받았어요.
            </Checkbox>
          )}
          <p className={styles.version}>동의서 버전 {sharing.required_version}</p>
        </Card>
      )}

      <Input
        label="제목"
        maxLength={100}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <Textarea
        label="내용 (선택)"
        rows={4}
        maxLength={2000}
        placeholder="작품에 대해 나누고 싶은 이야기를 적어 주세요."
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <Textarea
        label="피드백 받고 싶은 점 (선택)"
        rows={3}
        maxLength={1000}
        placeholder="예: 스케치 단계인데 구도가 괜찮은지 봐 주세요."
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />

      {formError && <p className={styles.error}>{formError}</p>}
      <Button type="submit" disabled={submitting || !consentOk}>
        {submitting ? '올리는 중…' : '올리기'}
      </Button>
    </form>
  )
}

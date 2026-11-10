import { useCallback, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Checkbox, Chip, Input, Textarea } from '../../../components/ui'
import { api } from '../../../lib/api'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createPost, getSharing, grantCommunitySharing } from '../api'
import styles from './PostWritePage.module.css'

// 공유 동의 고지 (docs/frontend-integration-v0.8.md §1, 법적 검토 전 초안)
const CONSENT_ITEMS = [
  ['공개되는 것', '공유용 작품 이미지, 게시물 제목·내용·질문, 실기 유형·작품 분류'],
  ['공개되지 않는 것', '원본 사진, 학원명, 연락처'],
  ['공개 범위', 'ART MATE를 쓰는 모든 사용자'],
  ['철회', '언제든 철회할 수 있고, 철회하면 게시물이 바로 내려가요.'],
]

// 완성 사진이 있는 내 작품 (features끼리 import하지 않도록 작품 목록 API를 직접 호출)
const listShareableArtworks = () =>
  api('/artworks?limit=100').then((page) => page.items.filter((a) => a.progress === 'FINAL'))

/** 커뮤니티 글쓰기: 작품 고르기 → (처음이면) 공유 동의 → 제목·내용·질문 */
export default function PostWritePage() {
  const [params, setParams] = useSearchParams()
  const artworkId = params.get('artwork')
  const load = useCallback(() => listShareableArtworks(), [])
  const { data: artworks } = useAsync(load)
  const selected = artworks?.find((a) => a.id === artworkId)

  return (
    <>
      <TopBar title="글쓰기" belowHeader />
      <main className={styles.body}>
        <section className={styles.section}>
          <h2 className={styles.heading}>공유할 작품</h2>
          {!artworks ? null : artworks.length === 0 ? (
            <Card variant="soft" className={styles.notice}>
              완성 사진이 있는 작품만 공유할 수 있어요.
              <Link to="/practice" className={styles.link}>
                작품 기록하러 가기
              </Link>
            </Card>
          ) : (
            <div className={styles.chips}>
              {artworks.map((a) => (
                <Chip
                  key={a.id}
                  selected={a.id === artworkId}
                  onClick={() => setParams({ artwork: a.id }, { replace: true })}
                >
                  {a.title} · {formatMonthDay(a.work_date)}
                </Chip>
              ))}
            </div>
          )}
        </section>

        {selected && <ShareForm key={selected.id} artwork={selected} />}
      </main>
    </>
  )
}

function ShareForm({ artwork }) {
  const navigate = useNavigate()
  const load = useCallback(() => getSharing(artwork.id), [artwork.id])
  const { data: sharing, error } = useAsync(load)
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

  async function handleSubmit(e) {
    e.preventDefault()
    if (!title.trim()) {
      setFormError('제목을 입력해 주세요.')
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
        artworkId: artwork.id,
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
          <span className={styles.label}>작성자 표시</span>
          <div className={styles.chips} role="radiogroup" aria-label="작성자 표시">
            <Chip
              role="radio"
              aria-checked={authorDisplay === 'ANONYMOUS'}
              selected={authorDisplay === 'ANONYMOUS'}
              onClick={() => setAuthorDisplay('ANONYMOUS')}
            >
              익명으로
            </Chip>
            <Chip
              role="radio"
              aria-checked={authorDisplay === 'NAME'}
              selected={authorDisplay === 'NAME'}
              onClick={() => setAuthorDisplay('NAME')}
            >
              내 닉네임으로
            </Chip>
          </div>
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
        placeholder="예: 유리컵의 비례가 어색한지 봐 주세요."
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />
      <p className={styles.hint}>피드백 받고 싶은 점을 적으면 "피드백 요청" 글로 올라가요.</p>

      {formError && <p className={styles.error}>{formError}</p>}
      <Button type="submit" disabled={submitting || !consentOk}>
        {submitting ? '올리는 중…' : '올리기'}
      </Button>
    </form>
  )
}

import { useCallback, useState } from 'react'
import { Flag, Heart, PenLine, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Checkbox, Chip, Select, Textarea } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { useOptions } from '../../../hooks/useOptions'
import { labelOf } from '../../../lib/options'
import { formatUploadedAt } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  addComment,
  adoptComment,
  deleteComment,
  deletePost,
  revokeCommunitySharing,
  updateComment,
  getPost,
  listComments,
  reportComment,
  reportPost,
  setLiked,
} from '../api'
import { REPORT_REASONS, postCategory } from '../labels'
import styles from './PostDetailPage.module.css'

export default function PostDetailPage() {
  const { postId } = useParams()
  const navigate = useNavigate()
  const load = useCallback(() => getPost(postId), [postId])
  const { data: post, error, reload } = useAsync(load)
  const [like, setLike] = useState(null) // 누른 뒤 서버 응답 { liked, like_count }
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  if (error) {
    return (
      <FullScreenStatus title="게시물을 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={() => navigate('/community')}>커뮤니티로</Button>
      </FullScreenStatus>
    )
  }
  if (!post) return <FullScreenStatus />

  const mine = post.author.is_me
  const liked = like?.liked ?? post.liked
  const likeCount = like?.like_count ?? post.like_count

  async function toggleLike() {
    setBusy(true)
    try {
      setLike(await setLiked(post.id, !liked))
    } catch (err) {
      setNotice(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    const message = post.artwork_id
      ? '게시물을 삭제할까요? 이 작품의 커뮤니티 공유도 함께 중단돼요. 다시 올리려면 공유 동의를 새로 해야 해요.'
      : '게시물을 삭제할까요? 삭제하면 되돌릴 수 없어요.'
    if (!window.confirm(message)) return
    try {
      // 내 게시물엔 artwork_id가 있음 → 공유 철회(게시물도 삭제됨). 없으면 게시물만 삭제
      if (post.artwork_id) await revokeCommunitySharing(post.artwork_id)
      else await deletePost(post.id)
      navigate('/community', { replace: true })
    } catch (err) {
      setNotice(toErrorMessage(err))
    }
  }

  return (
    <>
      <TopBar title="공개 작품" belowHeader />
      <main className={styles.body}>
        <div className={styles.head}>
          <span className={styles.category}>{postCategory(post)}</span>
          <h1 className={styles.title}>{post.title}</h1>
          <p className={styles.author}>
            <strong>{post.author.display_name}</strong> · {formatUploadedAt(post.created_at)}
          </p>
          {mine && post.status === 'HIDDEN' && (
            <Card variant="soft">숨겨진 게시물이에요. {post.hidden_reason}</Card>
          )}
        </div>

        {post.image?.url ? (
          <img src={post.image.url} alt={post.title} className={styles.image} />
        ) : (
          post.has_artwork && (
            <p className={styles.imageGone}>
              공유한 사진이 내려갔어요. 원본 사진을 지우면 공개용 이미지도 함께 내려가요.
              {mine && (
                <Link to={`/community/posts/${post.id}/edit`} className={styles.imageGoneLink}>
                  다른 사진 고르기
                </Link>
              )}
            </p>
          )
        )}
        {post.body && <p className={styles.text}>{post.body}</p>}
        {post.question && (
          <Card variant="soft" className={styles.question}>
            <span className={styles.questionLabel}>작성자의 질문</span>
            {post.question}
          </Card>
        )}

        <div className={styles.stats}>
          <span className={styles.statText}>
            <Heart size={14} fill="currentColor" aria-hidden /> {likeCount} · 댓글{' '}
            {post.comment_count}
          </span>
          <button
            type="button"
            className={`${styles.like} ${liked ? styles.liked : ''}`}
            onClick={toggleLike}
            disabled={busy}
            aria-pressed={liked}
          >
            좋아요 <Heart size={16} fill={liked ? 'currentColor' : 'none'} aria-hidden />
          </button>
        </div>
        <div className={styles.postActions}>
          {mine ? (
            <>
              <Link to={`/community/posts/${post.id}/edit`} className={styles.textButton}>
                <PenLine size={14} aria-hidden /> 수정
              </Link>
              <button type="button" className={styles.textButton} onClick={handleDelete}>
                <Trash2 size={14} aria-hidden /> 게시물 삭제
              </button>
            </>
          ) : (
            <ReportButton onReport={(reason) => reportPost(post.id, reason)} label="게시물 신고" />
          )}
        </div>
        {notice && <p className={styles.error}>{notice}</p>}

        <Comments post={post} onChanged={reload} />
      </main>
    </>
  )
}

function Comments({ post, onChanged }) {
  const options = useOptions()
  const load = useCallback(() => listComments(post.id), [post.id])
  const { data, reload } = useAsync(load)
  const [body, setBody] = useState('')
  const [type, setType] = useState('GENERAL')
  const [categories, setCategories] = useState([])
  const [anonymous, setAnonymous] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const comments = (data?.items ?? []).filter((c) => c.status !== 'DELETED')
  const categoryLabel = (code) => (options ? labelOf(options.weakness_categories, code) : code)

  async function run(action, message) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
      if (message) setNotice(message)
      reload()
      onChanged()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!body.trim()) return
    run(async () => {
      await addComment(post.id, {
        body: body.trim(),
        commentType: type,
        categories,
        isAnonymous: anonymous,
      })
      setBody('')
      setCategories([])
    })
  }

  const toggleCategory = (code) =>
    setCategories((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    )

  return (
    <section className={styles.comments}>
      <h2 className={styles.heading}>댓글</h2>
      {comments.length === 0 ? (
        <p className={styles.caption}>아직 댓글이 없습니다.</p>
      ) : (
        <ul className={styles.commentList}>
          {comments.map((c) => (
            <li key={c.id} className={styles.comment}>
              <div className={styles.commentHead}>
                <strong>{c.author.display_name}</strong>
                {c.author.is_me && c.author.is_anonymous && (
                  <span className={styles.caption}>(나 · 익명)</span>
                )}
                {c.comment_type === 'FEEDBACK' && (
                  <span className={styles.feedbackTag}>작품 피드백</span>
                )}
                {c.adopted && <span className={styles.adoptedTag}>채택됨</span>}
                <span className={styles.caption}>{formatUploadedAt(c.created_at)}</span>
              </div>
              {editingId === c.id ? (
                <CommentEditor
                  comment={c}
                  busy={busy}
                  onCancel={() => setEditingId(null)}
                  onSave={(patch) =>
                    run(async () => {
                      await updateComment(c.id, patch)
                      setEditingId(null)
                    })
                  }
                />
              ) : (
                <p className={styles.commentBody}>
                  {c.body}
                  {Date.parse(c.updated_at) - Date.parse(c.created_at) > 1000 && (
                    <span className={styles.caption}> (수정됨)</span>
                  )}
                </p>
              )}
              {c.categories.length > 0 && (
                <div className={styles.tags}>
                  {c.categories.map((code) => (
                    <span key={code} className={styles.tag}>
                      {categoryLabel(code)}
                    </span>
                  ))}
                </div>
              )}
              <div className={styles.commentActions}>
                {post.author.is_me && c.comment_type === 'FEEDBACK' && c.adopted === false && (
                  <button
                    type="button"
                    className={styles.adopt}
                    disabled={busy}
                    onClick={() =>
                      run(
                        () => adoptComment(c.id),
                        '피드백을 채택했어요. 내 작품의 첨삭 기록(다른 학생 의견)으로 저장됐어요.',
                      )
                    }
                  >
                    피드백 채택
                  </button>
                )}
                {c.author.is_me ? (
                  <>
                    {editingId !== c.id && (
                      <button
                        type="button"
                        className={styles.textButton}
                        disabled={busy}
                        onClick={() => setEditingId(c.id)}
                      >
                        수정
                      </button>
                    )}
                    <button
                      type="button"
                      className={styles.textButton}
                      disabled={busy}
                      onClick={() =>
                        window.confirm('댓글을 삭제할까요?') && run(() => deleteComment(c.id))
                      }
                    >
                      삭제
                    </button>
                  </>
                ) : (
                  <ReportButton onReport={(reason) => reportComment(c.id, reason)} label="신고" />
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {notice && <Card variant="soft">{notice}</Card>}

      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.chips} role="radiogroup" aria-label="댓글 종류">
          <Chip
            role="radio"
            aria-checked={type === 'GENERAL'}
            selected={type === 'GENERAL'}
            onClick={() => setType('GENERAL')}
          >
            의견
          </Chip>
          <Chip
            role="radio"
            aria-checked={type === 'FEEDBACK'}
            selected={type === 'FEEDBACK'}
            onClick={() => setType('FEEDBACK')}
          >
            작품 피드백
          </Chip>
        </div>
        {type === 'FEEDBACK' && (
          <div className={styles.tags}>
            {(options?.weakness_categories ?? []).map((o) => (
              <Chip
                key={o.code}
                selected={categories.includes(o.code)}
                onClick={() => toggleCategory(o.code)}
              >
                {o.label}
              </Chip>
            ))}
          </div>
        )}
        <div className={styles.inputRow}>
          <Textarea
            aria-label="댓글"
            rows={2}
            maxLength={1000}
            placeholder={
              type === 'FEEDBACK' ? '작품에 대한 피드백을 남겨 주세요' : '댓글을 입력해 주세요'
            }
            value={body}
            onChange={(e) => setBody(e.target.value)}
            className={styles.input}
          />
          <Button type="submit" size="md" fullWidth={false} disabled={busy || !body.trim()}>
            등록
          </Button>
        </div>
        <Checkbox checked={anonymous} onChange={setAnonymous}>
          익명으로 남기기
        </Checkbox>
        {error && <p className={styles.error}>{error}</p>}
        <p className={styles.footnote}>
          {anonymous ? '댓글은 익명 학생으로 보여요.' : '댓글은 내 닉네임으로 보여요.'}
          {type === 'FEEDBACK' &&
            ' 작성자가 채택하면 그 작품의 첨삭 기록(다른 학생 의견)으로 저장돼요.'}
        </p>
      </form>
    </section>
  )
}

/** 내 댓글 수정: 내용, 익명 여부 */
function CommentEditor({ comment, busy, onSave, onCancel }) {
  const [body, setBody] = useState(comment.body)
  const [anonymous, setAnonymous] = useState(comment.author.is_anonymous)
  return (
    <div className={styles.editor}>
      <Textarea
        aria-label="댓글 수정"
        rows={2}
        maxLength={1000}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <Checkbox checked={anonymous} onChange={setAnonymous}>
        익명으로 보이기
      </Checkbox>
      <div className={styles.reportActions}>
        <Button
          size="md"
          fullWidth={false}
          disabled={busy || !body.trim()}
          onClick={() => onSave({ body: body.trim(), isAnonymous: anonymous })}
        >
          저장
        </Button>
        <Button size="md" fullWidth={false} variant="soft" onClick={onCancel}>
          취소
        </Button>
      </div>
    </div>
  )
}

/** 신고 사유 선택 → 신고 (3건이 쌓이면 자동으로 숨겨짐) */
function ReportButton({ onReport, label }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [state, setState] = useState('')

  async function submit() {
    if (!reason) return
    setState('sending')
    try {
      await onReport(reason)
      setState('done')
    } catch (err) {
      setState(toErrorMessage(err))
    }
  }

  if (state === 'done') return <span className={styles.caption}>신고를 접수했어요.</span>
  if (!open) {
    return (
      <button type="button" className={styles.textButton} onClick={() => setOpen(true)}>
        <Flag size={14} aria-hidden /> {label}
      </button>
    )
  }
  return (
    <div className={styles.report}>
      <Select
        aria-label="신고 사유"
        placeholder="신고 사유 선택"
        options={REPORT_REASONS}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className={styles.reportActions}>
        <Button
          size="md"
          fullWidth={false}
          disabled={!reason || state === 'sending'}
          onClick={submit}
        >
          신고하기
        </Button>
        <Button size="md" fullWidth={false} variant="soft" onClick={() => setOpen(false)}>
          취소
        </Button>
      </div>
      {state && state !== 'sending' && <p className={styles.error}>{state}</p>}
    </div>
  )
}

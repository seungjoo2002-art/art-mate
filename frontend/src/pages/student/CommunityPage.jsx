import { useCallback, useEffect, useRef, useState } from 'react'
import { Copy, Heart, PenLine, Search, X } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import MascotCheer from '../../components/mascot/MascotCheer'
import { Button, Card } from '../../components/ui'
import { listFeed, setLiked } from '../../features/community/api'
import { authorName } from '../../features/community/anonName'
import { CATEGORY_FILTERS, postCategory } from '../../features/community/labels'
import { useAsync } from '../../hooks/useAsync'
import { formatTimeAgo } from '../../utils/date'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './CommunityPage.module.css'

const PAGE = 30

/** 잡지 호수: "2026 가을호" (3~5월 봄, 6~8월 여름, 9~11월 가을, 12~2월 겨울) */
function issueLabel(date = new Date()) {
  const m = date.getMonth() + 1
  const season =
    m >= 3 && m <= 5 ? '봄' : m >= 6 && m <= 8 ? '여름' : m >= 9 && m <= 11 ? '가을' : '겨울'
  return `${date.getFullYear()} ${season}호`
}
const VIEWS = [
  { key: 'board', label: '게시판' },
  { key: 'gallery', label: '작품 갤러리' },
]

export default function CommunityPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'gallery' ? 'gallery' : 'board'
  const category = CATEGORY_FILTERS.some((c) => c.code === params.get('category'))
    ? params.get('category')
    : 'all'
  const q = (params.get('q') ?? '').trim()
  const [limit, setLimit] = useState(PAGE)
  // 분류·검색은 서버에서 거름 (VER.2 P0 category, P1 q)
  const load = useCallback(
    () =>
      listFeed({
        limit,
        category: category === 'all' ? undefined : category,
        q,
      }),
    [limit, category, q],
  )
  const { data, error, reload } = useAsync(load)

  const setParam = (key, value, fallback) => {
    const next = new URLSearchParams(params)
    if (value === fallback) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const posts = data?.items ?? []
  // 갤러리는 사진이 있는 게시물만
  const visible = view === 'gallery' ? posts.filter((post) => post.image?.url) : posts

  // 커뮤니티는 다른 탭과 다른 세상: 리소 인쇄 잡지 (주황 + 남색, 종이결, 위쪽만 망점). 아래 탭바는 그대로
  return (
    <div className={styles.zine}>
      <header className={styles.mast}>
        <span className={styles.issue}>{issueLabel()}</span>
        <h1 className={styles.mastTitle}>커뮤니티</h1>
        <p className={styles.mastSub}>그림 그리는 우리끼리 만드는 잡지</p>
      </header>

      <div className={styles.tabs} role="tablist" aria-label="보기 방식">
        {VIEWS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={view === t.key}
            className={styles.tab}
            onClick={() => setParam('view', t.key, 'board')}
          >
            <span>{t.label}</span>
          </button>
        ))}
      </div>

      <SearchBox key={q} initial={q} onSearch={(text) => setParam('q', text, '')} />

      <div className={styles.chips} role="radiogroup" aria-label="게시판 분류">
        {CATEGORY_FILTERS.map((c) => (
          <button
            key={c.code}
            type="button"
            role="radio"
            aria-checked={category === c.code}
            className={styles.chip}
            onClick={() => setParam('category', c.code, 'all')}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* 글쓰기: 화면 오른쪽 아래 물감 방울 버튼 */}
      <Link to="/community/write" className={styles.write} aria-label="글쓰기" title="글쓰기">
        <PenLine size={22} aria-hidden />
      </Link>

      {error ? (
        <Card variant="soft" className={styles.message}>
          {toErrorMessage(error)}
          <Button variant="soft" size="md" onClick={reload}>
            다시 시도
          </Button>
        </Card>
      ) : !data ? null : visible.length === 0 ? (
        <div className={styles.empty}>
          <MascotCheer
            pose="curious"
            sub={
              q
                ? '다른 단어로 찾아보세요.'
                : view === 'gallery'
                  ? '사진이 있는 게시물이 여기에 모여요.'
                  : '질문을 남기거나 작품을 공유해 보세요.'
            }
          >
            {q ? `'${q}' 검색 결과가 없어요` : '아직 게시물이 없어요'}
          </MascotCheer>
        </div>
      ) : view === 'board' ? (
        <ul className={styles.board}>
          {visible.map((post) => (
            <li key={post.id}>
              <BoardPost post={post} />
            </li>
          ))}
        </ul>
      ) : (
        <Gallery posts={visible} />
      )}

      {data && data.total > data.items.length && (
        <Button variant="soft" onClick={() => setLimit((n) => n + PAGE)}>
          더 보기
        </Button>
      )}
      <p className={styles.footnote}>
        커뮤니티에는 공유용 작품 이미지와 글만 공개돼요. 원본 사진, 학원명, 연락처는 공개되지
        않습니다.
      </p>
    </div>
  )
}

/** 제목·내용 검색. 입력 후 엔터(검색)로 적용, 2자 이상일 때만 */
function SearchBox({ initial, onSearch }) {
  const [text, setText] = useState(initial)
  const [hint, setHint] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    const value = text.trim()
    if (value && value.length < 2) {
      setHint('두 글자 이상 입력해 주세요.')
      return
    }
    setHint('')
    onSearch(value)
  }

  return (
    <form className={styles.search} role="search" onSubmit={handleSubmit}>
      <Search size={18} aria-hidden className={styles.searchIcon} />
      <input
        type="search"
        enterKeyHint="search"
        className={styles.searchInput}
        placeholder="제목, 내용으로 검색"
        aria-label="게시물 검색"
        maxLength={50}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {initial && (
        <button
          type="button"
          className={styles.searchClear}
          aria-label="검색 지우기"
          onClick={() => onSearch('')}
        >
          <X size={16} />
        </button>
      )}
      {hint && <p className={styles.searchHint}>{hint}</p>}
    </form>
  )
}

/**
 * 작품 갤러리: 탐색 탭처럼 정사각형 3열 그리드 (불러온 순서 그대로, 인기 작품도 같은 크기).
 * 썸네일은 칸에 맞춰 잘라 보여 주기만 하고 원본은 게시물 화면에서 원래 비율로 봄
 */
function Gallery({ posts }) {
  return (
    <ul className={styles.grid}>
      {posts.map((post) => (
        <li key={post.id}>
          <GalleryItem post={post} />
        </li>
      ))}
    </ul>
  )
}

/** 갤러리 한 칸: 한 번 누르면 게시물로, 두 번 누르면 좋아요. 글씨 없이 그림만 */
function GalleryItem({ post }) {
  const like = useLike(post)
  // 지금 게시물 이미지는 1장. 여러 장(images)이 오면 첫 장을 보여 주고 겹친 사진 표시
  const multiple = (post.images?.length ?? 0) > 1
  return (
    <DoubleTapLink
      to={`/community/posts/${post.id}`}
      className={styles.tile}
      onDoubleTap={like.likeOnce}
      popKey={like.pop}
      label={post.title}
    >
      <img src={post.image.url} alt="" className={styles.tileImage} loading="lazy" />
      {multiple && (
        <span className={styles.multi} aria-label="사진 여러 장">
          <Copy size={16} strokeWidth={2.4} aria-hidden />
        </span>
      )}
    </DoubleTapLink>
  )
}

/**
 * 게시판 글 한 줄: [분류] 제목 → 작성자 · 시간 · 좋아요 · 댓글, 그림이 있으면 오른쪽 작은 정사각형.
 * 줄 전체가 게시물 링크 (한 번 누르면 이동, 두 번 누르면 좋아요)
 */
function BoardPost({ post }) {
  const like = useLike(post)
  const thumb = post.image?.url
  const excerpt = post.question || post.body
  return (
    <DoubleTapLink
      to={`/community/posts/${post.id}`}
      className={styles.line}
      onDoubleTap={like.likeOnce}
      popKey={like.pop}
    >
      <span className={styles.lineText}>
        <span className={styles.lineTitle}>
          <span className={styles.lineCategory}>[{postCategory(post)}]</span> {post.title}
        </span>
        {excerpt && <span className={styles.lineExcerpt}>{excerpt}</span>}
        <span className={styles.lineMeta}>
          <span className={styles.lineAuthor}>{authorName(post)}</span>
          <span aria-hidden>·</span>
          <time dateTime={post.created_at}>{formatTimeAgo(post.created_at)}</time>
          <span aria-hidden>·</span>
          <span className={like.liked ? styles.likedOn : ''}>좋아요 {like.count}</span>
          <span aria-hidden>·</span>
          <span>댓글 {post.comment_count}</span>
        </span>
      </span>
      {thumb && <img src={thumb} alt="" className={styles.lineThumb} loading="lazy" />}
    </DoubleTapLink>
  )
}

const DOUBLE_TAP_MS = 280

/**
 * 한 번 누르면 이동, 짧게 두 번 누르면 onDoubleTap (이동 안 함).
 * 두 번째 누름을 기다리느라 한 번 누를 때 이동이 DOUBLE_TAP_MS 만큼 늦어짐.
 * 두 번 누르면 가운데에 하트가 잠깐 떠오름 (popKey가 바뀔 때마다 다시 재생)
 */
function DoubleTapLink({ to, className, onDoubleTap, popKey, label, children }) {
  const navigate = useNavigate()
  const timer = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])

  function handleClick(e) {
    // 새 탭 열기(ctrl·cmd·shift·가운데 버튼)는 브라우저에 맡김
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
    e.preventDefault()
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
      onDoubleTap()
      return
    }
    timer.current = setTimeout(() => {
      timer.current = null
      navigate(to)
    }, DOUBLE_TAP_MS)
  }

  return (
    <Link
      to={to}
      className={`${className} ${styles.tapArea}`}
      onClick={handleClick}
      aria-label={label}
    >
      {children}
      {popKey > 0 && (
        <span key={popKey} className={styles.heartPop} aria-hidden>
          <Heart size={72} fill="currentColor" strokeWidth={0} />
        </span>
      )}
    </Link>
  )
}

/**
 * 목록 좋아요 상태: 먼저 화면에 반영하고, 실패하면 되돌림
 * toggle: 켜고 끄기 / likeOnce: 두 번 누르기 (켜기만, 이미 눌렀으면 하트만 띄움)
 */
function useLike(post) {
  const [state, setState] = useState({ liked: post.liked, count: post.like_count })
  const [pop, setPop] = useState(0)
  const busy = useRef(false)

  async function apply(next) {
    if (busy.current) return
    const prev = state
    setState({ liked: next, count: prev.count + (next ? 1 : -1) })
    busy.current = true
    try {
      const res = await setLiked(post.id, next)
      setState({ liked: res.liked, count: res.like_count })
    } catch {
      setState(prev)
    } finally {
      busy.current = false
    }
  }

  return {
    ...state,
    pop,
    toggle: () => apply(!state.liked),
    likeOnce: () => {
      setPop((n) => n + 1)
      if (!state.liked) apply(true)
    },
  }
}

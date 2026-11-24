import { useCallback, useEffect, useRef, useState } from 'react'
import { Flame, Heart, MessageCircle, PenLine, Search, X } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import MascotCheer from '../../components/mascot/MascotCheer'
import { MASCOT_POSES } from '../../components/mascot/poses'
import { Button, Card } from '../../components/ui'
import { listFeed, setLiked } from '../../features/community/api'
import { authorName } from '../../features/community/anonName'
import { CATEGORY_FILTERS, postCategory } from '../../features/community/labels'
import { useAsync } from '../../hooks/useAsync'
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
        <img src={MASCOT_POSES.reading} alt="" className={styles.mastCat} />
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
 * 작품 갤러리: 하트를 가장 많이 받은 작품 하나 크게 + 나머지는 원래 비율 그대로 두 줄 벽돌 쌓기
 * (불러온 게시물 안에서 고름. 하트가 0이거나 작품이 3개 미만이면 크게 보이는 칸 없이)
 */
function Gallery({ posts }) {
  const top = posts.reduce((best, p) => (p.like_count > (best?.like_count ?? 0) ? p : best), null)
  const featured = posts.length >= 3 && top ? top : null
  const rest = featured ? posts.filter((p) => p.id !== featured.id) : posts

  return (
    <>
      {featured && <GalleryItem post={featured} large />}
      <div className={styles.masonry}>
        {rest.map((post) => (
          <GalleryItem key={post.id} post={post} />
        ))}
      </div>
    </>
  )
}

/** 갤러리 한 칸: 한 번 누르면 게시물로, 두 번 누르면 좋아요 */
function GalleryItem({ post, large = false }) {
  const like = useLike(post)
  return (
    <div className={large ? styles.featured : styles.brick}>
      <DoubleTapLink
        to={`/community/posts/${post.id}`}
        className={styles.cover}
        onDoubleTap={like.likeOnce}
        popKey={like.pop}
      >
        {large && (
          <span className={styles.featuredBadge}>
            <Flame size={14} fill="currentColor" aria-hidden /> 인기
          </span>
        )}
        <img
          src={post.image.url}
          alt={post.title}
          className={large ? styles.featuredImage : styles.brickImage}
          loading={large ? undefined : 'lazy'}
        />
      </DoubleTapLink>
      {/* 사진 링크 위에 겹친 글씨 띠: 하트만 눌리고 나머지는 눌러도 아래 사진 링크로 감 */}
      <span className={`${styles.caption} ${large ? styles.captionLarge : ''}`}>
        <span className={styles.captionText}>
          <span className={styles.captionTitle}>{post.title}</span>
          {large && <span className={styles.captionAuthor}>{authorName(post)}</span>}
        </span>
        <LikeButton like={like} className={styles.captionLikes} />
      </span>
    </div>
  )
}

/**
 * 게시판 글 하나 = 잡지 지면. 그림만 색이 있고 나머지는 먹색·종이.
 * 맨 위 작성자 줄(인스타처럼, 익명이면 고양이 별명) → 그림 크게 → 분류 · 제목 · 미리보기 · 하트·댓글
 * 그림 없는 글은 얇은 테두리 상자. 한 번 누르면 게시물로, 두 번 누르면 좋아요
 */
function BoardPost({ post }) {
  const name = authorName(post)
  const hasImage = Boolean(post.image?.url)
  const like = useLike(post)
  return (
    <div className={`${styles.post} ${hasImage ? styles.spread : styles.note}`}>
      <DoubleTapLink
        to={`/community/posts/${post.id}`}
        className={styles.postLink}
        onDoubleTap={like.likeOnce}
        popKey={like.pop}
      >
        <span className={styles.byline}>
          <span className={styles.avatar} aria-hidden>
            {post.author?.is_anonymous ? (
              <img src={MASCOT_POSES.standing} alt="" className={styles.anonCat} />
            ) : (
              name.slice(0, 1)
            )}
          </span>
          <span className={styles.author}>{name}</span>
          <span className={styles.category}>{postCategory(post)}</span>
        </span>
        {hasImage && <img src={post.image.url} alt="" className={styles.photo} loading="lazy" />}
        <span className={styles.title}>{post.title}</span>
        {(post.question || post.body) && (
          <span className={styles.excerpt}>{post.question || post.body}</span>
        )}
      </DoubleTapLink>
      <span className={styles.meta}>
        <LikeButton like={like} className={styles.count} />
        <Link to={`/community/posts/${post.id}`} className={styles.count}>
          <MessageCircle size={13} aria-hidden />
          <span className={styles.srOnly}>댓글</span> {post.comment_count}
        </Link>
      </span>
    </div>
  )
}

const DOUBLE_TAP_MS = 280

/**
 * 한 번 누르면 이동, 짧게 두 번 누르면 onDoubleTap (이동 안 함).
 * 두 번째 누름을 기다리느라 한 번 누를 때 이동이 DOUBLE_TAP_MS 만큼 늦어짐.
 * 두 번 누르면 가운데에 하트가 잠깐 떠오름 (popKey가 바뀔 때마다 다시 재생)
 */
function DoubleTapLink({ to, className, onDoubleTap, popKey, children }) {
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
    <Link to={to} className={`${className} ${styles.tapArea}`} onClick={handleClick}>
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
 * toggle: 하트 버튼 (누르면 켜고 끄기) / likeOnce: 두 번 누르기 (켜기만, 이미 눌렀으면 하트만 띄움)
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

function LikeButton({ like, className = '' }) {
  return (
    <button
      type="button"
      className={`${className} ${styles.likeButton} ${like.liked ? styles.likedOn : ''}`}
      onClick={like.toggle}
      aria-pressed={like.liked}
      aria-label={`좋아요 ${like.count}`}
    >
      <Heart size={18} strokeWidth={2.2} fill={like.liked ? 'currentColor' : 'none'} aria-hidden />
      {like.count}
    </button>
  )
}

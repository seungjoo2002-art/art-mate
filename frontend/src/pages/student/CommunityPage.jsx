import { useCallback, useState } from 'react'
import { Flame, Heart, MessageCircle, PenLine, Search, X } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import MascotCheer from '../../components/mascot/MascotCheer'
import { Button, Card, PageIntro, SegmentedTabs } from '../../components/ui'
import PaintChips from '../../features/artworks/components/PaintChips'
import { listFeed } from '../../features/community/api'
import { CATEGORY_FILTERS, categoryColor, postCategory } from '../../features/community/labels'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './CommunityPage.module.css'

const PAGE = 30
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
    () => listFeed({ limit, category: category === 'all' ? undefined : category, q }),
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

  return (
    <>
      <PageIntro title="커뮤니티" />
      <SegmentedTabs
        variant="highlight"
        label="보기 방식"
        tabs={VIEWS}
        value={view}
        onChange={(key) => setParam('view', key, 'board')}
      />

      <SearchBox key={q} initial={q} onSearch={(text) => setParam('q', text, '')} />

      <PaintChips
        label="게시판 분류"
        options={CATEGORY_FILTERS}
        value={category}
        onChange={(code) => setParam('category', code, 'all')}
        colorOf={(code) => (code === 'all' ? null : categoryColor(code))}
        wrap={false}
      />

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
          {visible.map((post) => {
            const tone = categoryColor(post.category)
            return (
              <li key={post.id}>
                {/* 말풍선 대화: 왼쪽 작성자 동그라미, 오른쪽 말풍선 */}
                <Link
                  to={`/community/posts/${post.id}`}
                  className={styles.row}
                  style={{ '--tone': tone }}
                >
                  <span className={styles.avatar} aria-hidden>
                    {post.author.display_name.slice(0, 1)}
                  </span>
                  <span className={styles.bubble}>
                    <span className={styles.head}>
                      <span className={styles.author}>{post.author.display_name}</span>
                      <span className={styles.category}>{postCategory(post)}</span>
                    </span>
                    <span className={styles.title}>{post.title}</span>
                    {(post.question || post.body) && (
                      <span className={styles.excerpt}>{post.question || post.body}</span>
                    )}
                    {/* 사진 없는 글(has_artwork=false)은 사진 없음 */}
                    {post.image?.url && (
                      <img src={post.image.url} alt="" className={styles.photo} loading="lazy" />
                    )}
                    <span className={styles.meta}>
                      <span className={styles.likes}>
                        <Heart size={13} fill="currentColor" aria-hidden />
                        <span className={styles.srOnly}>좋아요</span> {post.like_count}
                      </span>
                      <span className={styles.count}>
                        <MessageCircle size={13} aria-hidden />
                        <span className={styles.srOnly}>댓글</span> {post.comment_count}
                      </span>
                    </span>
                  </span>
                </Link>
              </li>
            )
          })}
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
    </>
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
      {featured && (
        <Link to={`/community/posts/${featured.id}`} className={styles.featured}>
          <span className={styles.featuredBadge}>
            <Flame size={14} fill="currentColor" aria-hidden /> 인기
          </span>
          <img src={featured.image.url} alt={featured.title} className={styles.featuredImage} />
          <GalleryCaption post={featured} large />
        </Link>
      )}
      <div className={styles.masonry}>
        {rest.map((post) => (
          <Link key={post.id} to={`/community/posts/${post.id}`} className={styles.brick}>
            <img
              src={post.image.url}
              alt={post.title}
              className={styles.brickImage}
              loading="lazy"
            />
            <GalleryCaption post={post} />
          </Link>
        ))}
      </div>
    </>
  )
}

/** 사진 아래쪽을 어둡게 깔고 그 위에 제목 · 하트 (크게 보이는 칸은 작성자도) */
function GalleryCaption({ post, large = false }) {
  return (
    <span className={`${styles.caption} ${large ? styles.captionLarge : ''}`}>
      <span className={styles.captionText}>
        <span className={styles.captionTitle}>{post.title}</span>
        {large && <span className={styles.captionAuthor}>{post.author.display_name}</span>}
      </span>
      <span className={styles.captionLikes}>
        <Heart size={13} fill="currentColor" aria-hidden />
        <span className={styles.srOnly}>좋아요</span> {post.like_count}
      </span>
    </span>
  )
}

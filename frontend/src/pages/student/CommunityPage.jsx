import { useCallback, useState } from 'react'
import { Heart, LayoutGrid, List, Plus, Search, X } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { Button, Card, Chip, PageIntro, SegmentedTabs } from '../../components/ui'
import { listFeed } from '../../features/community/api'
import { CATEGORY_FILTERS, postCategory } from '../../features/community/labels'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './CommunityPage.module.css'

const PAGE = 30
const VIEWS = [
  {
    key: 'board',
    label: (
      <>
        <List size={18} aria-hidden /> 게시판 보기
      </>
    ),
  },
  {
    key: 'gallery',
    label: (
      <>
        <LayoutGrid size={18} aria-hidden /> 작품 갤러리
      </>
    ),
  },
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
      <PageIntro title="커뮤니티" description="작품을 나누고, 서로에게 의견을 남겨보세요." />
      <SegmentedTabs
        label="보기 방식"
        tabs={VIEWS}
        value={view}
        onChange={(key) => setParam('view', key, 'board')}
      />

      <SearchBox key={q} initial={q} onSearch={(text) => setParam('q', text, '')} />

      <div className={styles.toolbar}>
        <div className={styles.chips}>
          {CATEGORY_FILTERS.map((c) => (
            <Chip
              key={c.code}
              selected={category === c.code}
              onClick={() => setParam('category', c.code, 'all')}
            >
              {c.label}
            </Chip>
          ))}
        </div>
        <Link to="/community/write" className={styles.write}>
          <Plus size={18} aria-hidden /> 글쓰기
        </Link>
      </div>

      {error ? (
        <Card variant="soft" className={styles.message}>
          {toErrorMessage(error)}
          <Button variant="soft" size="md" onClick={reload}>
            다시 시도
          </Button>
        </Card>
      ) : !data ? null : visible.length === 0 ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>
            {q ? `'${q}' 검색 결과가 없어요.` : '아직 게시물이 없습니다.'}
          </p>
          <p className={styles.emptySub}>
            {q
              ? '다른 단어로 찾아보세요.'
              : view === 'gallery'
                ? '사진이 있는 게시물이 여기에 모여요.'
                : '질문을 남기거나 작품을 공유해 보세요.'}
          </p>
        </div>
      ) : view === 'board' ? (
        <ul className={styles.board}>
          {visible.map((post) => (
            <li key={post.id}>
              <Link to={`/community/posts/${post.id}`} className={styles.row}>
                <span className={styles.rowText}>
                  <span className={styles.category}>{postCategory(post)}</span>
                  <span className={styles.title}>{post.title}</span>
                  {(post.question || post.body) && (
                    <span className={styles.excerpt}>{post.question || post.body}</span>
                  )}
                  <span className={styles.meta}>
                    {post.author.display_name}
                    <span className={styles.count}>
                      <Heart size={13} fill="currentColor" aria-hidden /> {post.like_count}
                    </span>
                    <span>댓글 {post.comment_count}</span>
                  </span>
                </span>
                {/* 사진 없는 글(has_artwork=false)은 썸네일 없음 */}
                {post.image?.url && (
                  <img src={post.image.url} alt="" className={styles.thumb} loading="lazy" />
                )}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.gallery}>
          {visible.map((post) => (
            <Link key={post.id} to={`/community/posts/${post.id}`} className={styles.tile}>
              {post.image?.url ? (
                <img
                  src={post.image.url}
                  alt={post.title}
                  className={styles.tileImage}
                  loading="lazy"
                />
              ) : (
                <span className={styles.tileImage} aria-hidden />
              )}
              <span className={styles.tileTitle}>{post.title}</span>
              <span className={styles.meta}>
                <span className={styles.count}>
                  <Heart size={13} fill="currentColor" aria-hidden /> {post.like_count}
                </span>
                <span>댓글 {post.comment_count}</span>
              </span>
            </Link>
          ))}
        </div>
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

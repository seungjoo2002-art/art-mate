import { useCallback, useState } from 'react'
import { Heart, LayoutGrid, List, Plus } from 'lucide-react'
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

// 게시글 검색(q)은 VER.2 P1(백엔드 머지 전)이라 아직 제외
export default function CommunityPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'gallery' ? 'gallery' : 'board'
  const category = CATEGORY_FILTERS.some((c) => c.code === params.get('category'))
    ? params.get('category')
    : 'all'
  const [limit, setLimit] = useState(PAGE)
  // 분류는 서버에서 거름 (VER.2 P0)
  const load = useCallback(
    () => listFeed({ limit, category: category === 'all' ? undefined : category }),
    [limit, category],
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
          <p className={styles.emptyTitle}>아직 게시물이 없습니다.</p>
          <p className={styles.emptySub}>
            {view === 'gallery'
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

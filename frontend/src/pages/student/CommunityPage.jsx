import { useCallback, useState } from 'react'
import { Heart, LayoutGrid, List, Plus } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { Button, Card, Chip, PageIntro, SegmentedTabs } from '../../components/ui'
import { listFeed } from '../../features/community/api'
import { CATEGORY_FILTERS, matchesCategory, postCategory } from '../../features/community/labels'
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

// 디자인의 게시글 검색, "실기 질문"·"자유게시판"(사진 없는 글)은 백엔드가 없어 제외
export default function CommunityPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'gallery' ? 'gallery' : 'board'
  const category = CATEGORY_FILTERS.some((c) => c.key === params.get('category'))
    ? params.get('category')
    : 'all'
  const [limit, setLimit] = useState(PAGE)
  const load = useCallback(() => listFeed({ limit }), [limit])
  const { data, error, reload } = useAsync(load)

  const setParam = (key, value, fallback) => {
    const next = new URLSearchParams(params)
    if (value === fallback) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  // 분류는 서버 필터가 없어서 불러온 게시물 안에서 거름
  const posts = (data?.items ?? []).filter((post) => matchesCategory(post, category))

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
              key={c.key}
              selected={category === c.key}
              onClick={() => setParam('category', c.key, 'all')}
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
      ) : !data ? null : posts.length === 0 ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>아직 게시물이 없습니다.</p>
          <p className={styles.emptySub}>완성한 작품을 공유하고 의견을 나눠 보세요.</p>
        </div>
      ) : view === 'board' ? (
        <ul className={styles.board}>
          {posts.map((post) => (
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
                {post.image?.url && (
                  <img src={post.image.url} alt="" className={styles.thumb} loading="lazy" />
                )}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.gallery}>
          {posts.map((post) => (
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

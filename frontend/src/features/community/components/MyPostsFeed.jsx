import { useCallback } from 'react'
import { Heart, MessageCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { listMyPosts } from '../api'
import styles from './MyPostsFeed.module.css'

/** 아카이브 "공개 피드": 내가 커뮤니티에 공유한 작품 */
export default function MyPostsFeed() {
  const load = useCallback(() => listMyPosts(), [])
  const { data, error } = useAsync(load)

  if (error) return <Card variant="soft">{toErrorMessage(error)}</Card>
  if (!data) return null
  const posts = data.items.filter((post) => post.status !== 'DELETED')

  if (!posts.length) {
    return (
      <div className={styles.empty}>
        <p className={styles.emptyTitle}>아직 공개한 작품이 없습니다.</p>
        <p className={styles.emptySub}>커뮤니티에 공유한 작품이 이곳에 모여요.</p>
      </div>
    )
  }

  return (
    <div className={styles.grid}>
      {posts.map((post) => {
        const card = (
          <>
            <span className={styles.cover}>
              {post.image?.url ? (
                <img
                  src={post.image.url}
                  alt={post.title}
                  className={styles.image}
                  loading="lazy"
                />
              ) : (
                <span className={styles.image} aria-hidden />
              )}
              {post.status === 'HIDDEN' && (
                <Badge variant="overlay" className={styles.badge}>
                  숨김
                </Badge>
              )}
            </span>
            <span className={styles.title}>{post.title}</span>
            <span className={styles.meta}>
              {formatMonthDay(post.created_at.slice(0, 10))}
              <span className={styles.count}>
                <Heart size={14} aria-hidden /> {post.like_count}
              </span>
              <span className={styles.count}>
                <MessageCircle size={14} aria-hidden /> {post.comment_count}
              </span>
            </span>
            {post.status === 'HIDDEN' && post.hidden_reason && (
              <span className={styles.hidden}>{post.hidden_reason}</span>
            )}
          </>
        )
        return (
          <Link key={post.id} to={`/community/posts/${post.id}`} className={styles.card}>
            {card}
          </Link>
        )
      })}
    </div>
  )
}

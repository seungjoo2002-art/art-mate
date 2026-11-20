import { useCallback } from 'react'
import { Heart, MessageCircle } from 'lucide-react'
import { Badge, Card } from '../../../components/ui'
import SketchPage from '../../artworks/components/SketchPage'
import paperStyles from '../../artworks/components/SketchPage.module.css'
import { typeColor } from '../../artworks/practicalTypes'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { listMyPosts } from '../api'
import styles from './MyPostsFeed.module.css'

/** 아카이브 "공개 피드": 내가 커뮤니티에 공유한 작품. 전체 기록과 같은 뜯어낸 스케치북 한 장, 클립 대신 압정(공개) */
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
      {posts.map((post) => (
        <SketchPage
          key={post.id}
          to={`/community/posts/${post.id}`}
          seed={post.id}
          fastener="pin"
          accent={typeColor(post.practical_type)}
          media={
            <span className={styles.cover}>
              {post.image?.url ? (
                <img
                  src={post.image.url}
                  alt={post.title}
                  className={paperStyles.photo}
                  loading="lazy"
                />
              ) : (
                <span className={paperStyles.photo} aria-hidden />
              )}
              {post.status === 'HIDDEN' && (
                <Badge variant="overlay" className={styles.badge}>
                  숨김
                </Badge>
              )}
            </span>
          }
          date={formatMonthDay(post.created_at.slice(0, 10))}
          title={post.title}
          footer={
            <>
              <span className={styles.counts}>
                <span className={styles.likes}>
                  <Heart size={13} fill="currentColor" aria-hidden />
                  <span className={styles.srOnly}>좋아요</span> {post.like_count}
                </span>
                <span className={styles.comments}>
                  <MessageCircle size={13} aria-hidden />
                  <span className={styles.srOnly}>댓글</span> {post.comment_count}
                </span>
              </span>
              {post.status === 'HIDDEN' && post.hidden_reason && (
                <span className={styles.hidden}>{post.hidden_reason}</span>
              )}
            </>
          }
        />
      ))}
    </div>
  )
}

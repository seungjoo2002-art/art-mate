import { useCallback } from 'react'
import { GraduationCap, Images, Palette, PencilLine, Settings, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { listArtworks } from '../../features/artworks/api'
import { listTargetUniversities } from '../../features/auth/api'
import { listMyPosts } from '../../features/community/api'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { Group, Row } from './MyRows'
import styles from './MyPage.module.css'

// 디자인 중 백엔드가 없는 항목(학업 성적·모의고사, 실기 유형 관리, 실기시험 목표 시간,
// 시연 모드)은 API가 생기면 추가. 동의·알림·로그아웃은 설정 화면(/my/settings)
export default function MyPage() {
  const { profile } = useAuth()
  const options = useOptions()
  const loadTargets = useCallback(() => listTargetUniversities(), [])
  const { data: targets } = useAsync(loadTargets)

  const label = (list, code) => (code ? (options ? labelOf(options[list], code) : '') : null)
  const grade = label('grades', profile.grade)
  const practicalType = label('practical_types', profile.practical_type)
  const firstTarget = targets?.[0]
  const targetText = firstTarget
    ? `${firstTarget.university_name}${targets.length > 1 ? ` 외 ${targets.length - 1}곳` : ''}`
    : null

  return (
    <>
      {/* 프로필: 큰 동그라미 + 이름 + 학년·실기 유형 + 편집 */}
      <section className={styles.profile}>
        <span className={styles.avatar}>{profile.display_name.slice(0, 1)}</span>
        <div className={styles.profileText}>
          <h1 className={styles.name}>{profile.display_name}</h1>
          <p className={styles.sub}>
            {[grade, practicalType].filter(Boolean).join(' · ') || '학생'}
          </p>
        </div>
        <Link to="/my/edit" className={styles.edit} aria-label="프로필 편집">
          <PencilLine size={16} aria-hidden />
        </Link>
      </section>

      <Stats />

      <Group title="나의 입시 정보">
        <Row to="/my/edit" icon={Palette} label="주요 실기 유형" value={practicalType} />
        <Row to="/my/edit" icon={GraduationCap} label="목표 대학" value={targetText} />
        <Row to="/my/edit" icon={Target} label="학습 목표" value={profile.learning_goal} />
      </Group>
      <p className={styles.note}>지망 대학과 학습 목표는 커뮤니티에 공개하지 않습니다.</p>

      <Group>
        <Row to="/archive?tab=feed" icon={Images} label="내 공개 작품 피드" />
        <Row to="/my/settings" icon={Settings} label="설정" value="동의 · 알림 · 로그아웃" />
      </Group>
    </>
  )
}

/** 내 활동 숫자: 작품 수 · 공개 게시물 수 · 받은 하트 (게시물은 최근 50개 기준) */
function Stats() {
  const loadArtworks = useCallback(() => listArtworks({ limit: 1 }), [])
  const loadPosts = useCallback(() => listMyPosts({ limit: 50 }), [])
  const { data: artworks } = useAsync(loadArtworks)
  const { data: posts } = useAsync(loadPosts)

  const live = posts?.items.filter((p) => p.status !== 'DELETED')
  const likes = live?.reduce((sum, p) => sum + p.like_count, 0)
  const items = [
    { to: '/archive', label: '작품', value: artworks?.total },
    { to: '/archive?tab=feed', label: '공개 게시물', value: live?.length },
    { to: '/archive?tab=feed', label: '받은 하트', value: likes },
  ]

  return (
    <div className={styles.stats}>
      {items.map((s) => (
        <Link key={s.label} to={s.to} className={styles.stat}>
          <span className={styles.statValue}>{s.value ?? '–'}</span>
          <span className={styles.statLabel}>{s.label}</span>
        </Link>
      ))}
    </div>
  )
}

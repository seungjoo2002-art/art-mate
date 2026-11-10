import { useCallback } from 'react'
import { ChevronRight, Palette, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { Badge, Card, IconBox, PageIntro } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import { isCompleted } from '../../features/artworks/stages'
import { useAsync } from '../../hooks/useAsync'
import styles from './PracticePage.module.css'

export default function PracticePage() {
  const { profile } = useAuth()

  return (
    <>
      <PageIntro
        eyebrow="오늘의 실기"
        title="어떤 기록을 시작할까요?"
        description="작품의 과정이 쌓일수록 성장의 방향이 선명해져요."
      />
      {profile.user_type === 'STUDENT' ? (
        <>
          <Card as={Link} to="/artworks/new" className={styles.mode}>
            <IconBox icon={Palette} size="lg" />
            <span className={styles.modeText}>
              <Badge>오늘의 수업</Badge>
              <span className={styles.modeTitle}>일반 수업 모드</span>
              <span className={styles.modeSub}>단계별 사진과 선생님 피드백을 기록해요.</span>
            </span>
            <ChevronRight size={26} aria-hidden />
          </Card>
          <ContinueCard />
        </>
      ) : (
        <Card variant="soft">작품 기록은 학생 계정에서 사용할 수 있어요.</Card>
      )}
    </>
  )
}

/** 완성 전인 가장 최근 작품으로 이어가기 */
function ContinueCard() {
  const load = useCallback(() => listArtworks({ limit: 20 }), [])
  const { data } = useAsync(load)
  const artwork = data?.items.find((item) => !isCompleted(item))
  if (!artwork) return null

  return (
    <Card as={Link} to={`/artworks/${artwork.id}`} variant="soft" className={styles.continue}>
      <Sparkles size={28} aria-hidden />
      <span>
        <span className={styles.continueTitle}>지난 작품에서 이어가기</span>
        <span className={styles.continueSub}>{artwork.title}</span>
      </span>
    </Card>
  )
}

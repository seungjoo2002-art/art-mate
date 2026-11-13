import { useCallback } from 'react'
import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, PageIntro } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import ArtworkCard from '../../features/artworks/components/ArtworkCard'
import { formatMinutes, loadExamDefaults, totalMinutes } from '../../features/artworks/exam'
import { useAsync } from '../../hooks/useAsync'
import { formatMonthDay } from '../../utils/date'
import styles from './PracticePage.module.css'

// 시험 기본 목표 시간은 계정에 저장 (/users/me/exam-defaults), 시험 준비 화면에서 바꿀 수 있음
export default function PracticePage() {
  const { data: targets } = useAsync(loadExamDefaults)
  return (
    <>
      <PageIntro title="실기" description="작품을 자유롭게 기록하거나 실기시험을 진행하세요." />

      <LastExamCard />

      <ModeCard
        to="/artworks/new?mode=exam"
        title="실기시험 모드"
        description="아이디어·스케치·채색 목표 시간을 설정하고 단계별 사진, 메모와 녹음을 남깁니다."
        action={
          targets ? `목표 ${formatMinutes(totalMinutes(targets))} · 시험 시작하기` : '시험 시작하기'
        }
      />
      <ModeCard
        to="/artworks/new"
        title="새 작품 기록"
        description="시간 제한 없이 단계별 사진·첨삭·메모를 저장합니다."
        action="기록 시작하기"
      />

      <RecentArtworks />
    </>
  )
}

function ModeCard({ to, title, description, action }) {
  return (
    <Card as={Link} to={to} className={styles.mode}>
      <span className={styles.modeHeader}>
        <span className={styles.modeTitle}>{title}</span>
        <ChevronRight size={24} aria-hidden />
      </span>
      <span className={styles.modeDescription}>{description}</span>
      <span className={styles.modeAction}>{action}</span>
    </Card>
  )
}

/** 직전 모의시험의 소요 시간 / 제한 시간 */
function LastExamCard() {
  const load = useCallback(() => listArtworks({ limit: 1, workCategory: 'MOCK_EXAM' }), [])
  const { data } = useAsync(load)
  if (!data) return null
  const exam = data.items[0]

  return (
    <Card className={styles.lastExam}>
      <span className={styles.eyebrow}>직전 시험 참고</span>
      {exam ? (
        <Link to={`/artworks/${exam.id}`} className={styles.lastExamBody}>
          <span className={styles.lastExamTitle}>{exam.title}</span>
          <span className={styles.lastExamSub}>
            {formatMonthDay(exam.work_date)}
            {exam.time_limit_minutes && ` · 제한 ${formatMinutes(exam.time_limit_minutes)}`}
            {exam.actual_minutes
              ? ` · 소요 ${formatMinutes(exam.actual_minutes)}`
              : ' · 소요 시간 기록 없음'}
          </span>
          {exam.over_time_limit && <span className={styles.over}>제한 시간을 넘겼어요</span>}
        </Link>
      ) : (
        <>
          <span className={styles.lastExamTitle}>아직 시험 기록이 없습니다.</span>
          <span className={styles.lastExamSub}>
            첫 시험을 기록하면 다음 시험과 시간을 비교할 수 있습니다.
          </span>
        </>
      )}
    </Card>
  )
}

function RecentArtworks() {
  const load = useCallback(() => listArtworks({ limit: 4 }), [])
  const { data } = useAsync(load)

  return (
    <section className={styles.recent}>
      <div className={styles.recentHeader}>
        <h2 className={styles.recentTitle}>최근 내 작품</h2>
        <Link to="/archive" className={styles.more}>
          모든 기록 <ChevronRight size={18} aria-hidden />
        </Link>
      </div>
      {data?.items.length ? (
        <div className={styles.grid}>
          {data.items.map((artwork) => (
            <ArtworkCard key={artwork.id} artwork={artwork} />
          ))}
        </div>
      ) : (
        data && <p className={styles.lastExamSub}>아직 기록한 작품이 없어요.</p>
      )}
    </section>
  )
}

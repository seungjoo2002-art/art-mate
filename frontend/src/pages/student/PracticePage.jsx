import { useCallback } from 'react'
import { ChevronRight, PenLine, Timer } from 'lucide-react'
import { Link } from 'react-router-dom'
import mascotStanding from '../../assets/mascot/mascot-standing.webp'
import mascotTimer from '../../assets/mascot/mascot-timer.webp'
import { PageIntro } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import GalleryStrip from '../../features/artworks/components/GalleryStrip'
import { formatMinutes, loadExamDefaults, totalMinutes } from '../../features/artworks/exam'
import { tabColor } from '../../features/artworks/sectionTabs'
import tabStyles from '../../features/artworks/SectionTabs.module.css'
import { useAsync } from '../../hooks/useAsync'
import { formatMonthDay } from '../../utils/date'
import styles from './PracticePage.module.css'

// 시험 기본 목표 시간은 계정에 저장 (/users/me/exam-defaults), 시험 준비 화면에서 바꿀 수 있음
export default function PracticePage() {
  const { data: targets } = useAsync(loadExamDefaults)
  return (
    <>
      <PageIntro title="실기" description="작품을 자유롭게 기록하거나 실기시험을 진행하세요." />

      {/* 두 모드: 글자는 시험 왼쪽 · 새 작품 오른쪽, 반대쪽 빈자리에 고양이 (시험 = 시계 든 고양이) */}
      <div className={styles.modes}>
        <ModeCard
          to="/artworks/new?mode=exam"
          paint={tabColor(2)}
          icon={Timer}
          title="실기시험 모드"
          description="아이디어·스케치·채색 목표 시간을 설정하고 단계별 사진, 메모와 녹음을 남깁니다."
          action={
            targets ? `목표 ${formatMinutes(totalMinutes(targets))} · 시험 시작하기` : '시험 시작하기'
          }
          cat={{ src: mascotTimer, side: 'right' }}
        />
        <ModeCard
          to="/artworks/new"
          paint="var(--color-primary)"
          icon={PenLine}
          title="새 작품 기록"
          description="시간 제한 없이 단계별 사진·첨삭·메모를 저장합니다."
          action="기록 시작하기"
          cat={{ src: mascotStanding, side: 'left' }}
        />
      </div>

      <LastExamCard />

      <RecentArtworks />
    </>
  )
}

function ModeCard({ to, paint, icon: Icon, title, description, action, cat }) {
  return (
    <Link to={to} className={styles.mode} style={{ '--paint': paint }}>
      {cat && (
        <img
          className={`${styles.cat} ${cat.side === 'right' ? styles.catRight : styles.catLeft}`}
          src={cat.src}
          alt=""
        />
      )}
      <span className={styles.modeIcon}>
        <Icon size={24} aria-hidden />
      </span>
      <span className={styles.modeTitle}>{title}</span>
      <span className={styles.modeDescription}>{description}</span>
      <span className={styles.modeAction}>
        {action} <ChevronRight size={16} aria-hidden />
      </span>
    </Link>
  )
}

/** 직전 모의시험의 소요 시간 / 제한 시간 */
function LastExamCard() {
  const load = useCallback(() => listArtworks({ limit: 1, workCategory: 'MOCK_EXAM' }), [])
  const { data } = useAsync(load)
  if (!data) return null
  const exam = data.items[0]

  return (
    <section className={tabStyles.card} style={{ '--tab': tabColor(4) }}>
      <h2 className={tabStyles.tab}>직전 시험 참고</h2>
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
    </section>
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
        <GalleryStrip artworks={data.items} />
      ) : (
        data && <p className={styles.lastExamSub}>아직 기록한 작품이 없어요.</p>
      )}
    </section>
  )
}

import { useCallback } from 'react'
import { ChevronRight, GraduationCap, PenLine, Timer } from 'lucide-react'
import { Link } from 'react-router-dom'
import mascotMockExam from '../../assets/mascot/mascot-mockexam.webp'
import mascotNote from '../../assets/mascot/mascot-note.webp'
import mascotTimer from '../../assets/mascot/mascot-timer.webp'
import PawPrints from '../../components/decor/PawPrints'
import { PageIntro } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import GalleryStrip from '../../features/artworks/components/GalleryStrip'
import { formatMinutes } from '../../features/artworks/exam'
import { tabColor } from '../../features/artworks/sectionTabs'
import tabStyles from '../../features/artworks/SectionTabs.module.css'
import { useAsync } from '../../hooks/useAsync'
import { formatMonthDay } from '../../utils/date'
import styles from './PracticePage.module.css'

export default function PracticePage() {
  return (
    <>
      <PageIntro title="실기" description="작품을 자유롭게 기록하거나 실기시험을 진행하세요." />

      {/* 위: 실기시험 모드 · 실기 모의고사 반반 (아이콘 옆 제목, 아래 짧은 설명, 고양이는 오른쪽 아래), 아래: 새 작품 기록 (글자 오른쪽, 왼쪽에 빼꼼 고양이) */}
      <div className={styles.modes}>
        <div className={styles.pair}>
          <ModeCard
            small
            to="/artworks/new?mode=exam"
            paint={tabColor(2)}
            icon={Timer}
            title="실기시험 모드"
            description="시간 재며 단계별로 기록"
            action="시작하기"
            cat={{ src: mascotTimer, side: 'corner' }}
          />
          {/* 실기 모의고사: 기출·합격작 데이터(서버)가 아직 없어 구현 중 표시만 */}
          <ModeCard
            small
            soon
            paint="#6aaa82"
            icon={GraduationCap}
            title="실기 모의고사"
            description="기출로 보고 합격작과 비교"
            action="구현 중"
            cat={{ src: mascotMockExam, side: 'corner' }}
          />
        </div>
        <ModeCard
          to="/artworks/new"
          paint="var(--color-primary)"
          icon={PenLine}
          title="새 작품 기록"
          description="시간 제한 없이 자유롭게 기록"
          action="기록하기"
          cat={{ src: mascotNote, side: 'peek' }}
        />
      </div>

      <LastExamCard />

      <RecentArtworks />
    </>
  )
}

/**
 * small: 반 칸 (고양이 오른쪽 위 작게, 설명 짧게)
 * soon: 아직 구현 중 → 누를 수 없는 칸 + 회색 "구현 중" 알약
 */
function ModeCard({
  to,
  paint,
  icon: Icon,
  title,
  description,
  action,
  cat,
  small = false,
  soon = false,
}) {
  const Root = soon ? 'div' : Link
  return (
    <Root
      {...(soon ? { 'aria-disabled': true } : { to })}
      className={`${styles.mode} ${small ? styles.small : ''} ${soon ? styles.soon : ''}`}
      style={{ '--paint': paint }}
    >
      {cat && <img className={`${styles.cat} ${styles[`cat_${cat.side}`]}`} src={cat.src} alt="" />}
      {/* 반 칸은 아이콘 옆에 제목, 큰 칸은 아이콘 아래에 제목 */}
      <span className={styles.modeHead}>
        <span className={styles.modeIcon}>
          <Icon size={small ? 20 : 24} aria-hidden />
        </span>
        <span className={styles.modeTitle}>{title}</span>
      </span>
      {description && <span className={styles.modeDescription}>{description}</span>}
      <span className={styles.modeAction}>
        {action} {!soon && <ChevronRight size={16} aria-hidden />}
      </span>
    </Root>
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
        <h2 className={styles.recentTitle}>
          최근 내 작품
          <PawPrints />
        </h2>
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

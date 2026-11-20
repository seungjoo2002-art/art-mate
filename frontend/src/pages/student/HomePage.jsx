import { useCallback } from 'react'
import { ChevronRight, PenLine, Timer } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import Highlight from '../../components/decor/Highlight'
import PaintSplash from '../../components/decor/PaintSplash'
import PawPrints from '../../components/decor/PawPrints'
import MascotCheer from '../../components/mascot/MascotCheer'
import { listArtworks } from '../../features/artworks/api'
import GalleryStrip from '../../features/artworks/components/GalleryStrip'
import { tabColor } from '../../features/artworks/sectionTabs'
import tabStyles from '../../features/artworks/SectionTabs.module.css'
import {
  getGrowthSummary,
  getReport,
  getWeaknesses,
  listRecommendations,
} from '../../features/growth/api'
import { PERIOD_LABELS } from '../../features/growth/labels'
import { mockExamCount, pickNextPractice, summaryLine } from '../../features/growth/nextPractice'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { formatToday } from '../../utils/date'
import styles from './HomePage.module.css'

async function loadHome() {
  const [summary, analysis, recommendations, recent] = await Promise.all([
    getGrowthSummary(),
    getWeaknesses(),
    listRecommendations().catch(() => ({ items: [] })),
    listArtworks({ limit: 4 }),
  ])
  // 최근 성장 리포트에 AI 설명이 있으면 브리핑에 사용
  const latest = summary.latest_report
  const report =
    latest?.narrative_status === 'READY' ? await getReport(latest.id).catch(() => null) : null
  return { summary, analysis, recommendations: recommendations.items, recent: recent.items, report }
}

/** 홈 (VER.2): 고양이 인사 · 바로 시작 · 브리핑 · 학습 현황 · 오늘의 추천 연습 · 최근 작품 */
export default function HomePage() {
  const { profile } = useAuth()
  const load = useCallback(() => loadHome(), [])
  const { data } = useAsync(load)

  return (
    <>
      <MascotCheer as="h1" size="lg" pose="artist" eyebrow={formatToday()}>
        {profile.display_name}님, 오늘도 <Highlight>그려 볼까요?</Highlight>
        <PaintSplash />
      </MascotCheer>
      <QuickStart />

      {data && (
        <>
          <Briefing {...data} />
          <Stats analysis={data.analysis} />
          <TodayPractice analysis={data.analysis} recommendations={data.recommendations} />
          <RecentArtworks artworks={data.recent} />
          <p className={styles.footnote}>
            브리핑과 추천 연습은 확정된 첨삭 기록을 기준으로 정리합니다. 작품 사진으로 실력을 평가한
            결과가 아닙니다.
          </p>
        </>
      )}
    </>
  )
}

/** AI 설명이 있으면 "AI 브리핑", 없으면 기록 상태에 따른 "오늘의 브리핑" (AI 아님) */
function Briefing({ analysis, report }) {
  const { totals } = analysis
  const narrative = report?.ai_narrative?.content
  let brief
  if (narrative) {
    brief = {
      label: 'AI 브리핑',
      title: narrative.overview,
      text: narrative.improvement_comment || narrative.strengths_comment,
      meta: `${PERIOD_LABELS[report.period_type] ?? ''} 성장 리포트 기준`,
    }
  } else if (totals.artwork_count === 0 || totals.analyzed_artwork_count === 0) {
    brief = {
      label: '오늘의 브리핑',
      title:
        totals.artwork_count === 0 ? '첫 작품과 피드백을 등록해 주세요.' : '첨삭을 확정해 주세요.',
      text: '작품·첨삭을 기록하면 학습 이력을 정리하고 다음에 집중할 내용을 함께 살펴볼 수 있습니다.',
      meta: '분석할 기록 없음',
    }
  } else if (analysis.status !== 'READY') {
    brief = {
      label: '오늘의 브리핑',
      title: '첨삭이 쌓이고 있어요.',
      text: `확정한 첨삭이 있는 작품이 ${analysis.required_artwork_count}개가 되면 반복되는 항목을 분석해요.`,
      meta: `분석까지 ${analysis.required_artwork_count - totals.analyzed_artwork_count}개 남음`,
    }
  } else {
    brief = {
      label: '오늘의 브리핑',
      title: summaryLine(analysis),
      text: '분석 리포트에서 반복 항목과 변화 흐름을 확인해 보세요.',
      meta: `확정 첨삭 ${totals.approved_feedback_count}개 기준`,
    }
  }

  return (
    <section className={tabStyles.card} style={{ '--tab': tabColor(1) }}>
      <h2 className={tabStyles.tab}>{brief.label}</h2>
      <small className={tabStyles.cardMeta}>{brief.meta}</small>
      <p className={styles.cardTitle}>{brief.title}</p>
      {brief.text && <p className={styles.muted}>{brief.text}</p>}
      <Link to="/archive?tab=report" className={styles.pill}>
        분석 리포트 보기 <ChevronRight size={16} aria-hidden />
      </Link>
    </section>
  )
}

/** 바로 시작: 모눈 도화지 타일 두 개 (연습 탭의 두 모드와 같은 곳으로) */
function QuickStart() {
  return (
    <nav className={styles.quick} aria-label="바로 시작">
      <Link to="/artworks/new" className={styles.quickTile} style={{ '--paint': 'var(--color-primary)' }}>
        <span className={styles.quickIcon}>
          <PenLine size={22} aria-hidden />
        </span>
        <strong>새 작품 기록</strong>
        <small>단계별로 기록해요</small>
      </Link>
      <Link
        to="/artworks/new?mode=exam"
        className={styles.quickTile}
        style={{ '--paint': tabColor(2) }}
      >
        <span className={styles.quickIcon}>
          <Timer size={22} aria-hidden />
        </span>
        <strong>실기시험 연습</strong>
        <small>시간 재며 그려요</small>
      </Link>
    </nav>
  )
}

/** 학습 현황: 물감 점 타일 세 개 */
const STAT_PAINTS = ['var(--color-primary)', '#7c6ee6', '#3fa7d6']

function Stats({ analysis }) {
  const minutes = analysis.time_stats?.total_minutes ?? 0
  const time =
    minutes > 0 && minutes < 60 ? [minutes, '분'] : [Math.round((minutes / 60) * 10) / 10, '시간']
  return (
    <section className={styles.section}>
      <SectionHeader title="학습 현황" to="/archive" action="아카이브 보기" />
      <div className={styles.stats}>
        <Stat label="작품" value={analysis.totals.artwork_count} unit="점" paint={STAT_PAINTS[0]} />
        <Stat label="시험 기록" value={mockExamCount(analysis)} unit="회" paint={STAT_PAINTS[1]} />
        <Stat label="기록 시간" value={time[0]} unit={time[1]} paint={STAT_PAINTS[2]} />
      </div>
    </section>
  )
}

function TodayPractice({ analysis, recommendations }) {
  const options = useOptions()
  const card = pickNextPractice(analysis, recommendations)
  const chip = card.category
    ? options
      ? labelOf(options.weakness_categories, card.category)
      : null
    : '첫 작품 기록'

  return (
    <section className={tabStyles.card} style={{ '--tab': tabColor(3) }}>
      <h2 className={tabStyles.tab}>오늘의 추천 연습</h2>
      {chip && <small className={tabStyles.cardMeta}>{chip}</small>}
      <span className={styles.practiceLabel}>{card.label}</span>
      <p className={styles.cardTitle}>{card.title}</p>
      {card.method && <p className={styles.muted}>{card.method}</p>}
      <Link to={card.to} className={styles.cta}>
        {card.action} <ChevronRight size={18} aria-hidden />
      </Link>
    </section>
  )
}

function RecentArtworks({ artworks }) {
  return (
    <section className={styles.section}>
      <SectionHeader title="최근 작품" to="/archive" action="전체 보기" paws />
      {artworks.length ? (
        <GalleryStrip artworks={artworks} />
      ) : (
        <p className={styles.muted}>아직 기록한 작품이 없어요.</p>
      )}
    </section>
  )
}

function SectionHeader({ title, to, action, paws = false }) {
  return (
    <div className={styles.sectionHeader}>
      <h2 className={styles.heading}>
        {title}
        {paws && <PawPrints />}
      </h2>
      {to && (
        <Link to={to} className={styles.more}>
          {action} <ChevronRight size={18} aria-hidden />
        </Link>
      )}
    </div>
  )
}

function Stat({ label, value, unit, paint }) {
  return (
    <div className={styles.stat} style={{ '--paint': paint }}>
      <i className={styles.paint} aria-hidden />
      <span>
        <strong className={styles.statValue}>{value}</strong>
        <span className={styles.unit}>{unit}</span>
      </span>
      <span className={styles.small}>{label}</span>
    </div>
  )
}

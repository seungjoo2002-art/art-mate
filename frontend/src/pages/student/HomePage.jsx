import { useCallback } from 'react'
import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { Card } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import ArtworkCard from '../../features/artworks/components/ArtworkCard'
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

/** 홈 (VER.2): 인사 · 브리핑 · 학습 현황 · 오늘의 추천 연습 · 최근 작품 */
export default function HomePage() {
  const { profile } = useAuth()
  const load = useCallback(() => loadHome(), [])
  const { data } = useAsync(load)

  return (
    <>
      <header className={styles.greeting}>
        <p className={styles.date}>{formatToday()}</p>
        <h1 className={styles.hello}>안녕하세요, {profile.display_name}님.</h1>
      </header>

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
    <Card className={styles.card}>
      <span className={styles.briefLabel}>
        <span className={styles.dot} aria-hidden />
        {brief.label}
      </span>
      <p className={styles.cardTitle}>{brief.title}</p>
      {brief.text && <p className={styles.muted}>{brief.text}</p>}
      <div className={styles.cardFooter}>
        <span className={styles.small}>{brief.meta}</span>
        <Link to="/archive?tab=report" className={styles.more}>
          분석 리포트 보기 <ChevronRight size={18} aria-hidden />
        </Link>
      </div>
    </Card>
  )
}

function Stats({ analysis }) {
  const minutes = analysis.time_stats?.total_minutes ?? 0
  const time =
    minutes > 0 && minutes < 60 ? [minutes, '분'] : [Math.round((minutes / 60) * 10) / 10, '시간']
  return (
    <section className={styles.section}>
      <SectionHeader title="학습 현황" to="/archive" action="아카이브 보기" />
      <Card className={styles.stats}>
        <Stat label="작품" value={analysis.totals.artwork_count} unit="점" />
        <Stat label="시험 기록" value={mockExamCount(analysis)} unit="회" />
        <Stat label="기록 시간" value={time[0]} unit={time[1]} />
      </Card>
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
    <section className={styles.section}>
      <SectionHeader title="오늘의 추천 연습" />
      <Card className={styles.card}>
        <span className={styles.practiceLabel}>{card.label}</span>
        <p className={styles.cardTitle}>{card.title}</p>
        {card.method && <p className={styles.muted}>{card.method}</p>}
        <div className={styles.cardFooter}>
          {chip ? <span className={styles.chip}>{chip}</span> : <span />}
          <Link to={card.to} className={styles.more}>
            {card.action} <ChevronRight size={18} aria-hidden />
          </Link>
        </div>
      </Card>
    </section>
  )
}

function RecentArtworks({ artworks }) {
  return (
    <section className={styles.section}>
      <SectionHeader title="최근 작품" to="/archive" action="전체 보기" />
      {artworks.length ? (
        <div className={styles.grid}>
          {artworks.map((a) => (
            <ArtworkCard key={a.id} artwork={a} />
          ))}
        </div>
      ) : (
        <p className={styles.muted}>아직 기록한 작품이 없어요.</p>
      )}
    </section>
  )
}

function SectionHeader({ title, to, action }) {
  return (
    <div className={styles.sectionHeader}>
      <h2 className={styles.heading}>{title}</h2>
      {to && (
        <Link to={to} className={styles.more}>
          {action} <ChevronRight size={18} aria-hidden />
        </Link>
      )}
    </div>
  )
}

function Stat({ label, value, unit }) {
  return (
    <div className={styles.stat}>
      <span className={styles.small}>{label}</span>
      <span>
        <strong className={styles.statValue}>{value}</strong>
        <span className={styles.unit}>{unit}</span>
      </span>
    </div>
  )
}

import { useCallback } from 'react'
import { ChevronRight } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getGrowthTimeline, getWeaknesses, listRecommendations } from '../api'
import { TREND_LABELS } from '../labels'
import EvidenceList from './EvidenceList'
import MentionTrendChart from './MentionTrendChart'
import Notes from './Notes'
import styles from './AnalysisReport.module.css'

const ACTIVE_RECOMMENDATION = ['ADOPTED', 'IN_REVIEW', 'DRAFT']

async function loadReport() {
  const [analysis, timeline, recommendations] = await Promise.all([
    getWeaknesses(),
    getGrowthTimeline(),
    listRecommendations().catch(() => ({ items: [] })),
  ])
  return { analysis, timeline: timeline.items, recommendations: recommendations.items }
}

/**
 * 아카이브 "분석 리포트" 탭 (VER.2). 확정된 첨삭만 근거로, 규칙 기반 문구 (AI 채점 아님)
 * 성장 리포트(기간별)·맞춤 연습 과제 화면은 아래 링크로
 */
export default function AnalysisReport() {
  const load = useCallback(() => loadReport(), [])
  const { data, error, reload } = useAsync(load)

  if (error) {
    return (
      <Card variant="soft" className={styles.message}>
        {toErrorMessage(error)}
        <Button variant="soft" size="md" onClick={reload}>
          다시 시도
        </Button>
      </Card>
    )
  }
  if (!data) return null

  const { analysis, timeline, recommendations } = data
  const { totals } = analysis
  const ready = analysis.status === 'READY'
  const mockExams =
    analysis.work_category_distribution?.find((d) => d.work_category === 'MOCK_EXAM')
      ?.artwork_count ?? 0
  const repeated = analysis.weaknesses.filter((w) => w.repeated)
  const compared = analysis.weaknesses.filter((w) => w.previous && w.trend !== 'INSUFFICIENT_DATA')
  const recentImprovements = analysis.weaknesses
    .flatMap((w) => w.evidence)
    .sort((a, b) => (b.work_date ?? '').localeCompare(a.work_date ?? ''))
    .slice(0, 3)
  const withFeedback = timeline.filter((t) => t.feedbacks?.length)
  const trend = withFeedback
    .slice(0, 8)
    .reverse()
    .map((t) => ({
      label: formatMonthDay(t.work_date).replace('월 ', '/').replace('일', ''),
      title: t.title,
      positive: t.feedbacks.reduce((n, f) => n + (f.strengths?.length ?? 0), 0),
      improve: t.feedbacks.reduce((n, f) => n + (f.weaknesses?.length ?? 0), 0),
    }))

  return (
    <div className={styles.report}>
      <p className={styles.eyebrow}>MY GROWTH · 첨삭 기록 기반</p>

      <Cheer totals={totals} ready={ready} required={analysis.required_artwork_count} />

      <Section title="학습 기록 요약">
        <div className={styles.stats}>
          <Stat label="기록된 작품" value={`${totals.artwork_count}점`} />
          <Stat label="첨삭 연결" value={`${totals.analyzed_artwork_count}점`} />
          <Stat label="실기시험" value={`${mockExams}회`} />
        </div>
      </Section>

      <Section title="피드백 언급 추이">
        <Card className={styles.card}>
          {trend.length >= 2 ? (
            <MentionTrendChart points={trend} />
          ) : (
            <div className={styles.empty}>
              <p className={styles.emptyTitle}>추이 분석을 위한 기록이 부족해요.</p>
              <p className={styles.muted}>
                서로 다른 작품에 첨삭을 2건 이상 확정하면 선 그래프로 확인할 수 있습니다.
              </p>
            </div>
          )}
          <p className={styles.small}>
            최근 작품의 긍정 언급과 개선 요청 횟수입니다. 강사마다 평가 초점이 다를 수 있으므로 실제
            실력 점수·향상률이 아닙니다.
          </p>
        </Card>
      </Section>

      <Section title="핵심 한 줄 요약">
        <Card className={styles.card}>
          <p className={styles.headline}>{summaryLine(analysis, ready)}</p>
          <p className={styles.muted}>
            작품과 첨삭의 실제 문장을 근거로 분석하며, 사진만으로 작품 수준을 평가하지 않습니다.
          </p>
        </Card>
      </Section>

      <Section title="반복 지적·집중 항목">
        <Card className={styles.card}>
          {repeated.length ? (
            repeated.map((w) => (
              <div key={w.category} className={styles.row}>
                <span className={styles.rowTitle}>{w.label}</span>
                <span className={styles.muted}>
                  작품 {totals.analyzed_artwork_count}개 중 {w.artwork_count}개에서 지적
                </span>
              </div>
            ))
          ) : (
            <p className={styles.muted}>분류 가능한 세부 첨삭 항목이 아직 없습니다.</p>
          )}
        </Card>
      </Section>

      <Section title="과거와 최근 피드백 비교">
        <Card className={styles.card}>
          {compared.length ? (
            compared.map((w) => (
              <div key={w.category} className={styles.row}>
                <span className={styles.rowTitle}>{w.label}</span>
                <span className={styles.muted}>
                  이전 {w.previous.analyzed_artwork_count}개 중 {w.previous.artwork_count}개 → 최근{' '}
                  {w.recent.analyzed_artwork_count}개 중 {w.recent.artwork_count}개 ·{' '}
                  {TREND_LABELS[w.trend]}
                </span>
              </div>
            ))
          ) : (
            <>
              <p className={styles.cardTitle}>더 많은 작품 기록이 필요합니다</p>
              <p className={styles.muted}>
                새로운 작품과 첨삭을 추가하면 과거 기록과 최근 기록을 나누어 비교할 수 있습니다.
              </p>
            </>
          )}
        </Card>
      </Section>

      <Section title="긍정적으로 언급된 부분">
        <Card className={styles.card}>
          {analysis.strengths?.length ? (
            analysis.strengths.map((s) => (
              <div key={s.category} className={styles.block}>
                <span className={styles.rowTitle}>
                  {s.label} · 작품 {s.artwork_count}개
                </span>
                <EvidenceList evidence={s.evidence} limit={2} />
              </div>
            ))
          ) : (
            <p className={styles.muted}>현재 긍정적 표현으로 분류된 첨삭이 없습니다.</p>
          )}
        </Card>
      </Section>

      <Section title="최근 개선 요청과 근거">
        <Card className={styles.card}>
          {recentImprovements.length ? (
            <EvidenceList evidence={recentImprovements} />
          ) : (
            <p className={styles.muted}>현재 개선 요청으로 분류된 첨삭이 없습니다.</p>
          )}
        </Card>
      </Section>

      <Section title="다음 학습 우선순위">
        <NextPriority analysis={analysis} recommendations={recommendations} />
      </Section>

      <Section title="분석에 사용된 작품·첨삭 원문">
        {withFeedback.length ? (
          <div className={styles.sources}>
            {withFeedback.map((t) => (
              <Card key={t.artwork_id} className={styles.card}>
                <Link to={`/artworks/${t.artwork_id}`} className={styles.rowTitle}>
                  {t.title} · {formatMonthDay(t.work_date)}
                </Link>
                {t.feedbacks.map((f) => (
                  <Link key={f.id} to={`/feedbacks/${f.id}`} className={styles.source}>
                    {f.summary}
                  </Link>
                ))}
              </Card>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>아직 분석할 첨삭이 없습니다.</p>
        )}
      </Section>

      <div className={styles.links}>
        <Link to="/growth/reports" className={styles.link}>
          기간별 성장 리포트 <ChevronRight size={16} aria-hidden />
        </Link>
        <Link to="/growth/recommendations" className={styles.link}>
          맞춤 연습 과제 <ChevronRight size={16} aria-hidden />
        </Link>
      </div>
      <Notes notes={analysis.notes} />
    </div>
  )
}

/** 기록 상태에 따른 응원 문구 */
function Cheer({ totals, ready, required }) {
  const [title, text] =
    totals.artwork_count === 0
      ? [
          '작품 하나부터 차근차근 시작해 보세요!',
          '피드백 기록이 쌓이면 반복되는 항목과 변화 흐름을 확인할 수 있습니다.',
        ]
      : !ready
        ? [
            '첨삭을 확정하면 분석이 시작돼요!',
            `확정한 첨삭이 있는 작품 ${totals.analyzed_artwork_count}개 / ${required}개. 녹음이나 글 첨삭을 AI로 정리하고 확정해 보세요.`,
          ]
        : [
            '기록이 차곡차곡 쌓이고 있어요!',
            `확정 첨삭 ${totals.approved_feedback_count}개를 바탕으로 정리했어요.`,
          ]
  return (
    <Card className={styles.card}>
      <span className={styles.cheerLabel}>ART MATE의 응원</span>
      <p className={styles.cheerTitle}>{title}</p>
      <p className={styles.muted}>{text}</p>
    </Card>
  )
}

/** 규칙 기반 한 줄 요약 (AI 아님) */
function summaryLine(analysis, ready) {
  if (!ready) return '피드백 기록이 쌓이면 반복되는 항목과 변화 흐름을 확인할 수 있습니다.'
  const top = analysis.weaknesses.find((w) => w.category === analysis.top_weaknesses[0])
  const strength = analysis.strengths?.[0]
  if (!top && !strength) return '아직 반복해서 언급된 항목이 없어요.'
  const parts = []
  if (top) parts.push(`최근 첨삭에서 '${top.label}'이(가) 가장 자주 언급됐어요`)
  if (strength) parts.push(`'${strength.label}'은(는) 긍정적으로 언급됐어요`)
  return `${parts.join(', ')}.`
}

/** 진행 중인 맞춤 연습 과제 → 다음 연습 목표 → 첫 기록 안내 */
function NextPriority({ analysis, recommendations }) {
  const navigate = useNavigate()
  const rec = recommendations
    .filter((r) => ACTIVE_RECOMMENDATION.includes(r.status))
    .sort(
      (a, b) => ACTIVE_RECOMMENDATION.indexOf(a.status) - ACTIVE_RECOMMENDATION.indexOf(b.status),
    )[0]
  const goal = analysis.next_goals?.[0]

  let card
  if (rec) {
    card = {
      label: `맞춤 연습 과제 · ${rec.status === 'ADOPTED' ? '진행 중' : '새 추천'}`,
      title: rec.title,
      goal: rec.learning_goal || rec.description,
      method: rec.method_steps?.join(' → '),
      action: '추천 연습 이어서 하기',
      to: `/growth/recommendations/${rec.id}`,
    }
  } else if (goal) {
    card = {
      label: '기록 기반 제안',
      title: goal.goal,
      goal: '반복해서 지적된 항목을 다음 작품에서 의식적으로 점검해 보세요.',
      method: '맞춤 연습 과제를 받아 짧게 연습한 뒤 작품에 적용해 보세요.',
      action: '맞춤 연습 과제 받기',
      to: '/growth/recommendations',
    }
  } else {
    card = {
      label: '첫 기록 · 기록 기반 제안',
      title: '첫 작품의 제작 과정 기록하기',
      goal: '단계별 사진과 간단한 첨삭부터 저장해 보세요.',
      method: '사진 1장과 메모 1개부터 시작해도 괜찮습니다.',
      action: '추천 연습 시작 · 새 작품 기록',
      to: '/artworks/new',
    }
  }

  return (
    <Card className={styles.card}>
      <span className={styles.cheerLabel}>{card.label}</span>
      <p className={styles.cardTitle}>{card.title}</p>
      {card.goal && (
        <p className={styles.muted}>
          <strong>목표</strong> · {card.goal}
        </p>
      )}
      {card.method && (
        <p className={styles.muted}>
          <strong>연습 방법</strong> · {card.method}
        </p>
      )}
      <Button withArrow onClick={() => navigate(card.to)}>
        {card.action}
      </Button>
    </Card>
  )
}

function Section({ title, children }) {
  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>{title}</h2>
      {children}
    </section>
  )
}

function Stat({ label, value }) {
  return (
    <Card className={styles.stat}>
      <span className={styles.small}>{label}</span>
      <strong className={styles.statValue}>{value}</strong>
    </Card>
  )
}

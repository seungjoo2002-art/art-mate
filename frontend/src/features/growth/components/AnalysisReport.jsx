import { useCallback } from 'react'
import { ChevronRight } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import MascotCheer from '../../../components/mascot/MascotCheer'
import { Button, Card } from '../../../components/ui'
import tabStyles from '../../artworks/SectionTabs.module.css'
import { tabColor } from '../../artworks/sectionTabs'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getGrowthTimeline, getWeaknesses, listRecommendations } from '../api'
import { compareRows, lastActivity, mistakeRows, percent } from '../growthView'
import { TREND_LABELS } from '../labels'
import { mockExamCount, pickNextPractice, summaryLine } from '../nextPractice'
import EvidenceList from './EvidenceList'
import { PeriodFeedbackBars, TagMentionBars } from './GrowthCharts'
import MentionTrendChart from './MentionTrendChart'
import Notes from './Notes'
import PracticeTips from './PracticeTips'
import styles from './AnalysisReport.module.css'

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
  const mockExams = mockExamCount(analysis)
  // v1.0 9개 태그 기준 (이전 응답이면 기존 카테고리)
  const mistakes = mistakeRows(analysis)
  const repeated = mistakes.filter((w) => w.repeated)
  const compared = compareRows(analysis)
  const cautions = analysis.comparison_context?.cautions ?? []
  const latest = lastActivity(timeline)
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
      <Cheer totals={totals} ready={ready} required={analysis.required_artwork_count} />

      <Section title="학습 기록 요약" color={1}>
        <div className={styles.stats}>
          <Stat label="기록된 작품" value={totals.artwork_count} unit="점" paint="var(--color-primary)" />
          <Stat label="누적 첨삭" value={totals.approved_feedback_count} unit="건" paint="#7c6ee6" />
          <Stat label="첨삭 연결" value={totals.analyzed_artwork_count} unit="점" paint="#e0607e" />
          <Stat label="실기시험" value={mockExams} unit="회" paint="#3fa7d6" />
        </div>
        {latest && (
          <Link to={`/artworks/${latest.artworkId}`} className={styles.link}>
            최근 활동 · {formatMonthDay(latest.workDate)} {latest.title}
            {latest.feedbackCount ? ` (첨삭 ${latest.feedbackCount}건)` : ''}
            <ChevronRight size={16} aria-hidden />
          </Link>
        )}
      </Section>

      <Section title="작품별 피드백 변화" color={2}>
        <div className={styles.body}>
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
        </div>
      </Section>

      <Section title="핵심 한 줄 요약" color={3}>
        <div className={styles.body}>
          <p className={styles.headline}>{summaryLine(analysis)}</p>
          <p className={styles.muted}>
            작품과 첨삭의 실제 문장을 근거로 분석하며, 사진만으로 작품 수준을 평가하지 않습니다.
          </p>
        </div>
      </Section>

      <Section title="반복 실수 (9개 항목)" color={4}>
        <div className={styles.body}>
          {repeated.length ? (
            repeated.map((w) => (
              <div key={w.key} className={styles.row}>
                <div className={styles.rowHead}>
                  <span className={styles.rowTitle}>{w.label}</span>
                  <strong className={styles.ratio}>{percent(w.ratio)}</strong>
                </div>
                <span className={styles.meter} aria-hidden>
                  <span style={{ width: percent(w.ratio) }} />
                </span>
                <span className={styles.small}>
                  작품 {totals.analyzed_artwork_count}개 중 {w.count}개에서 지적
                </span>
              </div>
            ))
          ) : (
            <p className={styles.muted}>
              {mistakes.length
                ? '아직 2개 이상의 작품에서 반복된 개선할 점은 없어요.'
                : '분류 가능한 세부 첨삭 항목이 아직 없습니다.'}
            </p>
          )}
          {mistakes.length > repeated.length && (
            <p className={styles.small}>
              한 작품에서만 지적:{' '}
              {mistakes
                .filter((w) => !w.repeated)
                .map((w) => w.label)
                .join(', ')}
            </p>
          )}
        </div>
      </Section>

      <Section title="최근 연습 과제" color={5}>
        <PracticeTips tips={analysis.practice_tips ?? []} onChanged={reload} />
      </Section>

      <Section title="과거와 최근 피드백 비교" color={6}>
        <div className={styles.body}>
          {compared.length ? (
            compared.map((w) => (
              <div key={w.key} className={styles.row}>
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
          {cautions.map((text) => (
            <p key={text} className={styles.small}>
              ⚠ {text}
            </p>
          ))}
          {compared.length > 0 && (
            <p className={styles.small}>
              덜 언급된 항목이 실력이 늘었다는 뜻은 아니에요. 작품 난이도와 첨삭 분량에 따라 달라질 수
              있어요.
            </p>
          )}
        </div>
      </Section>

      {analysis.tags?.length > 0 && (
        <Section title="항목별 잘한 점·개선할 점" color={7}>
          <div className={styles.body}>
            <TagMentionBars analysis={analysis} />
            <p className={styles.small}>
              확정한 첨삭에서 각 항목이 언급된 작품 수예요 (작품당 한 번).
            </p>
          </div>
        </Section>
      )}

      {analysis.timeline?.length > 0 && (
        <Section title="기간별 첨삭 횟수" color={8}>
          <div className={styles.body}>
            <PeriodFeedbackBars analysis={analysis} />
            <p className={styles.small}>작업한 날짜 기준, 확정한 강사 첨삭 수예요.</p>
          </div>
        </Section>
      )}

      <Section title="긍정적으로 언급된 부분" color={9}>
        <div className={styles.body}>
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
        </div>
      </Section>

      <Section title="최근 개선 요청과 근거" color={10}>
        <div className={styles.body}>
          {recentImprovements.length ? (
            <EvidenceList evidence={recentImprovements} />
          ) : (
            <p className={styles.muted}>현재 개선 요청으로 분류된 첨삭이 없습니다.</p>
          )}
        </div>
      </Section>

      <Section title="다음 학습 우선순위" color={11}>
        <NextPriority analysis={analysis} recommendations={recommendations} />
      </Section>

      <Section title="분석에 사용된 작품·첨삭 원문" color={12}>
        {withFeedback.length ? (
          <div className={styles.sources}>
            {withFeedback.map((t) => (
              <div key={t.artwork_id} className={styles.sourceItem}>
                <Link to={`/artworks/${t.artwork_id}`} className={styles.rowTitle}>
                  {t.title} · {formatMonthDay(t.work_date)}
                </Link>
                {t.feedbacks.map((f) => (
                  <Link key={f.id} to={`/feedbacks/${f.id}`} className={styles.source}>
                    {f.summary}
                  </Link>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>아직 분석할 첨삭이 없습니다.</p>
        )}
      </Section>

      <div className={styles.links}>
        <Link to="/growth/reports" className={styles.pill}>
          기간별 성장 리포트 <ChevronRight size={16} aria-hidden />
        </Link>
        <Link to="/growth/recommendations" className={styles.pill}>
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
    <MascotCheer pose="check" size="lg" eyebrow="ART MATE의 응원" sub={text}>
      {title}
    </MascotCheer>
  )
}

/** 진행 중인 맞춤 연습 과제 → 다음 연습 목표 → 첫 기록 안내 */
function NextPriority({ analysis, recommendations }) {
  const navigate = useNavigate()
  const card = pickNextPractice(analysis, recommendations)

  return (
    <div className={styles.body}>
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
      <Button size="compact" withArrow onClick={() => navigate(card.to)}>
        {card.action}
      </Button>
    </div>
  )
}

/** 스케치북 인덱스 탭 카드. 탭 색은 순서대로 돌아가며 (sectionTabs.js) */
function Section({ title, color, children }) {
  return (
    <section className={tabStyles.card} style={{ '--tab': tabColor(color) }}>
      <h2 className={tabStyles.tab}>{title}</h2>
      {children}
    </section>
  )
}

/** 물감 점 숫자 타일 (홈 학습 현황과 같은 모양) */
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

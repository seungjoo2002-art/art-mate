import { useCallback } from 'react'
import { Bot, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import MascotCheer from '../../../components/mascot/MascotCheer'
import { Button, Card } from '../../../components/ui'
import tabStyles from '../../artworks/SectionTabs.module.css'
import { tabColor } from '../../artworks/sectionTabs'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getAnalysisReport, getWeaknesses } from '../api'
import { TAG_LABELS } from '../growthView'
import {
  aiCommentView,
  improvingLine,
  repeatedLine,
  reportIntro,
  strengthLine,
  trendSteps,
} from '../insightsView'
import EvidenceList from './EvidenceList'
import Notes from './Notes'
import PracticeTips from './PracticeTips'
import styles from './AnalysisReport.module.css'

async function loadReport() {
  const [report, analysis] = await Promise.all([
    getAnalysisReport(),
    // '연습 과제로 담기'·완료 체크 상태는 기존 분석 API에만 있음 (없어도 리포트는 보여 준다)
    getWeaknesses().catch(() => null),
  ])
  return { report, practiceTips: analysis?.practice_tips ?? null }
}

/**
 * 아카이브 "분석 리포트" 탭 (v1.2, GET /growth/me/analysis-report).
 * 확정된 강사 첨삭만 근거로 서버가 판정한 결과를 그대로 보여 준다 (조회 때 AI 호출 없음).
 * 점수·백분율·성장률을 화면에서 만들지 않는다. 숫자는 서버가 준 작품 수·날짜뿐.
 */
export default function AnalysisReport() {
  const { profile } = useAuth()
  // 계정이 바뀌면 다시 불러온다 (이전 사용자 리포트를 보여 주지 않음)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(() => loadReport(), [profile?.id])
  const { data, error, reload } = useAsync(load)

  if (error) {
    return (
      <Card variant="soft" className={styles.message}>
        분석 리포트를 불러오지 못했어요. {toErrorMessage(error)}
        <Button variant="soft" size="md" onClick={reload}>
          다시 시도
        </Button>
      </Card>
    )
  }
  if (!data) return null

  const { report, practiceTips } = data
  const intro = reportIntro(report)
  const ready = report.status === 'READY'

  return (
    <div className={styles.report}>
      <MascotCheer pose="check" size="lg" eyebrow="ART MATE의 응원" sub={intro.text}>
        {intro.title}
      </MascotCheer>

      <Section title="전체 학습 기록" color={1}>
        <RecordSummary report={report} />
      </Section>

      <Section title="최근 첨삭 요약" color={2}>
        <RecentFeedbacks items={report.recent_feedbacks} />
      </Section>

      {ready ? (
        <>
          <Section title="반복적으로 지적받은 부분" color={3}>
            <TagList
              tags={report.repeated_mistakes}
              empty="아직 2개 이상의 작품에서 반복된 지적은 없어요."
              render={(t) => (
                <>
                  <span className={styles.small}>{repeatedLine(t, formatMonthDay)}</span>
                  <Themes themes={t.themes} />
                  <RelatedArtworks artworks={t.related_artworks} />
                  <EvidenceList evidence={t.issue_evidence} limit={2} withSource />
                </>
              )}
            />
          </Section>

          <Section title="긍정적인 평가를 받은 부분" color={4}>
            <TagList
              tags={report.strengths}
              empty="2개 이상의 작품에서 긍정 평가를 받은 부분이 아직 없어요. 지적이 없다는 이유로 강점이라고 하지 않아요."
              render={(t) => (
                <>
                  <span className={styles.small}>{strengthLine(t, formatMonthDay)}</span>
                  <EvidenceList evidence={t.positive_evidence} limit={2} withSource />
                </>
              )}
            />
          </Section>

          <Section title="개선되고 있는 부분" color={5}>
            <TagList
              tags={report.improving}
              empty="지적을 받은 뒤 긍정 평가로 이어진 부분이 아직 없어요."
              render={(t) => (
                <>
                  <span className={styles.small}>{improvingLine(t, formatMonthDay)}</span>
                  <TrendSteps tag={t} />
                  <EvidenceList evidence={t.positive_evidence} limit={2} withSource />
                </>
              )}
            />
          </Section>

          <Section title="여전히 개선이 필요한 부분" color={6}>
            <TagList
              tags={report.needs_work}
              empty="가장 최근 첨삭에서 다시 지적된 부분은 없어요."
              render={(t) => (
                <>
                  <span className={styles.small}>{repeatedLine(t, formatMonthDay)}</span>
                  <Themes themes={t.themes} />
                  <EvidenceList evidence={t.issue_evidence} limit={1} withSource />
                  {t.practice_evidence.length > 0 && (
                    <>
                      <span className={styles.subLabel}>선생님의 수정 지시</span>
                      <EvidenceList evidence={t.practice_evidence} limit={1} />
                    </>
                  )}
                </>
              )}
            />
          </Section>
        </>
      ) : (
        <Section title="성장 분석" color={3}>
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>{report.message ?? '분석할 기록이 아직 없어요.'}</p>
            <p className={styles.muted}>
              확정한 강사 첨삭이 있는 작품 {report.counts.analyzed_artwork_count}개 /{' '}
              {report.criteria.required_artwork_count}개
            </p>
          </div>
        </Section>
      )}

      <Section title="다음 연습 추천" color={7}>
        {practiceTips?.length ? (
          <PracticeTips tips={practiceTips} onChanged={reload} />
        ) : report.next_practice.length ? (
          <div className={styles.body}>
            <EvidenceList evidence={report.next_practice} limit={5} />
          </div>
        ) : (
          <p className={styles.muted}>
            확정한 첨삭에 '다음 작품 연습 과제'가 생기면 여기에 모아 보여 드려요.
          </p>
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
      <p className={styles.small}>
        판정 기준: 반복·강점은 작품 {report.criteria.repeated_min_artworks}개 이상, 전체 분석은 확정
        강사 첨삭이 있는 작품 {report.criteria.required_artwork_count}개 이상.{' '}
        {report.criteria.improvement_rule}
      </p>
      <Notes notes={report.notes} />
    </div>
  )
}

/**
 * 전체 학습 기록: 한눈에 보이는 상태 (AI 분석 아님, 서버가 준 숫자만)
 * - 작품 몇 점 중 몇 점이 선생님 첨삭을 받았는지 + 막대
 * - 지금 할 일(확인할 첨삭) · 정리 중 · 분석까지 남은 작품 수
 * - 저장된 AI 코멘트
 */
function RecordSummary({ report }) {
  const { counts, status } = report
  const ai = aiCommentView(report.ai_narrative)
  const total = counts.artwork_count
  const withFeedback = counts.analyzed_artwork_count
  const needed = Math.max(report.criteria.required_artwork_count - withFeedback, 0)
  const percent = total ? Math.round((withFeedback / total) * 100) : 0

  return (
    <div className={styles.body}>
      <div className={styles.record}>
        <p className={styles.recordHead}>
          작품 <strong>{total}점</strong> 중 <strong>{withFeedback}점</strong>이 선생님 첨삭을
          받았어요
        </p>
        <div
          className={styles.bar}
          role="progressbar"
          aria-label="첨삭 받은 작품"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={withFeedback}
        >
          <span className={styles.barFill} style={{ width: `${percent}%` }} />
        </div>
        <p className={styles.small}>
          실기시험 {counts.mock_exam_count}회 · 연습 {counts.practice_artwork_count}점
        </p>
      </div>

      {(counts.pending_review_count > 0 ||
        counts.processing_count > 0 ||
        (status !== 'READY' && needed > 0)) && (
        <ul className={styles.todo}>
          {counts.pending_review_count > 0 && (
            <li className={styles.todoAction}>
              <strong>확인할 첨삭 {counts.pending_review_count}개</strong>
              <span>확인하면 리포트에 반영돼요</span>
            </li>
          )}
          {counts.processing_count > 0 && (
            <li>
              <strong>정리 중 {counts.processing_count}개</strong>
              <span>녹음을 글로 바꾸고 정리하고 있어요</span>
            </li>
          )}
          {status !== 'READY' && needed > 0 && (
            <li>
              <strong>첨삭 받은 작품 {needed}점 더</strong>
              <span>쌓이면 반복 실수·강점 분석을 시작해요</span>
            </li>
          )}
        </ul>
      )}

      {ai && (
        <div className={styles.ai}>
          <span className={styles.subLabel}>
            <Bot size={14} aria-hidden /> {ai.label}
          </span>
          {ai.text && <p className={styles.muted}>{ai.text}</p>}
          {ai.note && <p className={styles.small}>{ai.note}</p>}
        </div>
      )}
    </div>
  )
}

function RecentFeedbacks({ items }) {
  if (!items.length) return <p className={styles.muted}>아직 확정한 첨삭이 없어요.</p>
  return (
    <div className={styles.sources}>
      {items.map((f) => (
        <div key={f.feedback_id} className={styles.sourceItem}>
          <Link to={`/artworks/${f.artwork_id}`} className={styles.rowTitle}>
            {f.artwork_title} · {formatMonthDay(f.work_date)}
          </Link>
          <Link to={`/feedbacks/${f.feedback_id}`} className={styles.source}>
            {f.summary}
          </Link>
          {f.tags.length > 0 && (
            <div className={styles.chips}>
              {f.tags.map((tag) => (
                <span key={tag} className={styles.chip}>
                  {TAG_LABELS[tag] ?? tag}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function TagList({ tags, empty, render }) {
  if (!tags.length) return <p className={styles.muted}>{empty}</p>
  return (
    <div className={styles.body}>
      {tags.map((t) => (
        <div key={t.tag} className={styles.block}>
          <span className={styles.rowTitle}>{t.label}</span>
          {render(t)}
        </div>
      ))}
    </div>
  )
}

function Themes({ themes }) {
  if (!themes?.length) return null
  return (
    <div className={styles.chips}>
      {themes.map((theme) => (
        <span key={theme.code} className={styles.chip}>
          {theme.label} · 작품 {theme.artwork_count}개
        </span>
      ))}
    </div>
  )
}

function RelatedArtworks({ artworks }) {
  if (!artworks?.length) return null
  return (
    <div className={styles.chips}>
      {artworks.slice(0, 4).map((a) => (
        <Link key={a.id} to={`/artworks/${a.id}`} className={styles.artworkLink}>
          {a.title} · {formatMonthDay(a.work_date)}
        </Link>
      ))}
    </div>
  )
}

/** 작업일 순 지적·칭찬 (서버가 준 사건 그대로) */
function TrendSteps({ tag }) {
  const steps = trendSteps(tag)
  if (steps.length < 2) return null
  return (
    <ol className={styles.steps} aria-label={`${tag.label} 첨삭 흐름 (오래된 순)`}>
      {steps.map((s) => (
        <li key={s.key} className={styles.step} data-polarity={s.polarity}>
          <i aria-hidden />
          <span>{formatMonthDay(s.date)}</span>
          <strong>{s.label}</strong>
        </li>
      ))}
    </ol>
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

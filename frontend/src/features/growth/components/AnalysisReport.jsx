import { useCallback, useState } from 'react'
import {
  BookOpen,
  Bot,
  ChevronDown,
  ChevronRight,
  MessageSquareText,
  Sprout,
  Target,
  ThumbsUp,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import MascotCheer from '../../../components/mascot/MascotCheer'
import { MASCOT_POSES } from '../../../components/mascot/poses'
import { Button, Card } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createReport, getAnalysisReport, getWeaknesses, listReports } from '../api'
import { TAG_LABELS } from '../growthView'
import { PERIOD_LABELS } from '../labels'
import { aiCommentView, josa, reportIntro, splitSentences, trendSteps } from '../insightsView'
import Notes from './Notes'
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

      {ready && <Glance report={report} />}

      <Section icon={BookOpen} title="전체 학습 기록" tone={TONE.base}>
        <RecordSummary report={report} />
      </Section>

      <Section icon={MessageSquareText} title="최근 받은 첨삭" tone={TONE.recent}>
        <RecentFeedbacks items={report.recent_feedbacks} />
      </Section>

      {ready ? (
        <>
          <ChatSection
            id="report-strengths"
            cat="good"
            title="잘하고 있어요!"
            tone={TONE.good}
            tags={report.strengths}
            say={(t) => marked(t, '이', '가', ' 좋아요!')}
            quote={(t) => t.positive_evidence}
            empty="작품이 더 쌓이면 잘하는 점을 찾아 줄게요!"
          />

          <ChatSection
            id="report-improving"
            right
            cat="cheer"
            title="점점 좋아지고 있어요!"
            tone={TONE.up}
            tags={report.improving}
            say={(t) => marked(t, '이', '가', ' 좋아지고 있어요!')}
            note={(t) =>
              t.improvement_confirmed ? '계속 칭찬받는 중이에요' : '조금 더 지켜볼게요'
            }
            quote={(t) => t.positive_evidence}
            top={(t) => <TrendSteps tag={t} />}
            empty="지적받은 부분이 칭찬으로 바뀌면 알려 줄게요."
          />

          <ChatSection
            id="report-needs"
            cat="artist"
            title="이것만 보완하면 더 좋아져요"
            tone={TONE.issue}
            tags={report.needs_work}
            say={(t) => marked(t, '을', '를', ' 조금 더 다듬어 봐요')}
            quote={(t) => t.issue_evidence}
            tip={(t) => t.practice_evidence?.[0]?.content}
            empty="최근 첨삭에서 다시 지적받은 부분이 없어요. 아주 좋아요!"
          />
        </>
      ) : (
        <Section icon={Target} title="성장 분석" tone={TONE.issue}>
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>{report.message ?? '분석할 기록이 아직 없어요.'}</p>
            <p className={styles.muted}>
              첨삭 받은 작품 {report.counts.analyzed_artwork_count}점 /{' '}
              {report.criteria.required_artwork_count}점
            </p>
          </div>
        </Section>
      )}

      <NextPractice tips={practiceTips} fallback={report.next_practice} />

      <PeriodReport />

      <div className={styles.footer}>
        <Notes notes={report.notes} />
        <details className={styles.criteria}>
          <summary>분석 기준 보기</summary>
          <p>
            반복·강점은 작품 {report.criteria.repeated_min_artworks}개 이상에서 나온 것만 보여요.
            전체 분석은 선생님 첨삭을 받은 작품이 {report.criteria.required_artwork_count}점 이상일
            때 시작해요. {report.criteria.improvement_rule}
          </p>
        </details>
      </div>
    </div>
  )
}

/** 다음에 연습할 것: 선생님이 남긴 '다음 작품 연습 과제' 문장만 간단히 (담기·체크 없음) */
function NextPractice({ tips, fallback }) {
  const items = tips?.length
    ? tips.map((t) => ({ key: t.tip.item_id, text: t.tip.content, tag: TAG_LABELS[t.tag] }))
    : fallback.map((e) => ({ key: e.item_id, text: e.content }))
  // 섹션 제목 없이: 왼쪽에 안경 쓴 선생님 고양이, 오른쪽에 말풍선이 차례로.
  // 그 아래 '맞춤 연습 과제' 카드에는 책상에서 연습하는 고양이
  return (
    <section className={styles.talkWrap} aria-label="다음에 연습할 것">
      <div className={styles.talk}>
        <img src={MASCOT_POSES.teacher} alt="" className={styles.talkCat} />
        <div className={styles.talkBubbles}>
          <p className={`${styles.bubble} ${styles.bubbleLead}`}>
            {items.length
              ? '이런 걸 연습해 봐요!'
              : '선생님이 다음 연습할 걸 알려 주면 내가 여기서 알려 줄게요!'}
          </p>
          {items.slice(0, 5).map((item, i) => (
            <p key={item.key} className={styles.bubble} style={{ '--i': i + 1 }}>
              {item.tag && <span className={styles.practiceTag}>{item.tag}</span>}
              {item.text}
            </p>
          ))}
        </div>
      </div>

      {/* 맞춤 연습 과제로: 테이프 붙은 노란 포스트잇 + 옆에서 기다리는 책상 고양이 */}
      <Link to="/growth/recommendations" className={styles.postit}>
        <span className={styles.postitNote}>
          <span className={styles.postitTitle}>연습장 펼치러 가기!</span>
          <span className={styles.postitSub}>
            맞춤 연습 과제 <ChevronRight size={12} aria-hidden />
          </span>
        </span>
        <img src={MASCOT_POSES.practice} alt="" className={styles.postitCat} />
      </Link>
    </section>
  )
}

/**
 * 고양이 채팅 섹션 (카드 없음, 누르지 않아도 다 보임).
 * 맨 위: 고양이 + 큰 말풍선(title). 그 아래 항목마다 고양이가 차례로 말함:
 *   한마디(say, note) → 선생님 문장 말풍선(첫 1개, 출처: 작품 · 날짜) → 수정 지시(tip)가 있으면 '이렇게 해 보래요'
 * right: 고양이·말풍선을 오른쪽으로 (섹션마다 번갈아). 근거 더 있으면 '다른 첨삭 N개'로 펼침
 */
function ChatSection({
  id,
  cat,
  title,
  tone,
  tags,
  say,
  note,
  quote,
  top,
  tip,
  empty,
  right = false,
}) {
  return (
    <section
      id={id}
      className={`${styles.chatSection} ${right ? styles.chatRight : ''}`}
      style={{ '--tone': tone }}
      aria-label={title}
    >
      <div className={styles.chatHead}>
        <img
          src={MASCOT_POSES[cat]}
          alt=""
          className={`${styles.chatCat} ${cat === 'good' ? styles.chatCatBig : ''}`}
        />
        <p className={styles.chatTitle}>{title}</p>
      </div>
      {tags.length ? (
        <div className={styles.chatItems}>
          {tags.map((t, i) => (
            <ChatItem
              key={t.tag}
              tag={t}
              index={i}
              say={say}
              note={note}
              quote={quote}
              top={top}
              tip={tip}
            />
          ))}
        </div>
      ) : (
        <p className={styles.chatEmpty}>{empty}</p>
      )}
    </section>
  )
}

function ChatItem({ tag: t, index, say, note, quote, top, tip }) {
  const [open, setOpen] = useState(false)
  const evidence = quote(t) ?? []
  const shown = open ? evidence.slice(0, 3) : evidence.slice(0, 1)
  const more = Math.min(evidence.length, 3) - 1
  const fix = tip?.(t)
  return (
    <div className={styles.chatItem} style={{ '--i': index }}>
      <p className={styles.chatSay}>
        {say(t)}
        {note && <span className={styles.chatNote}>{note(t)}</span>}
      </p>
      {top?.(t)}
      {shown.map((e) => (
        <Link key={e.item_id} to={`/feedbacks/${e.feedback_id}`} className={styles.chatQuote}>
          <span>“{e.content}”</span>
          {e.artwork_title && (
            <span className={styles.chatSource}>
              {e.artwork_title}
              {e.work_date && ` · ${formatMonthDay(e.work_date)}`} 첨삭에서
            </span>
          )}
        </Link>
      ))}
      {fix && (
        <p className={styles.chatTip}>
          <span className={styles.chatSource}>선생님이 이렇게 해 보래요</span>
          {fix}
        </p>
      )}
      {more > 0 && (
        <button type="button" className={styles.chatMore} onClick={() => setOpen((v) => !v)}>
          {open ? '접기' : `다른 첨삭 ${more}개`}
        </button>
      )}
    </div>
  )
}

/**
 * 고양이 한마디: 영역 이름(구도·원근·공간감…)에 형광펜 + 조사 + 나머지 말.
 * '기타'(OTHER)는 무엇인지 몰라 '기타가 좋아요!' 같은 문장을 만들지 않고 이름만
 */
function marked(tag, withBatchim, withoutBatchim, rest) {
  const name = <mark className={styles.hl}>{tag.label}</mark>
  if (tag.tag === 'OTHER') return name
  const particle = josa(tag.label, withBatchim, withoutBatchim).slice(tag.label.length)
  return (
    <>
      {name}
      {particle}
      {rest}
    </>
  )
}

const PERIODS = ['WEEK', 'MONTH', 'ALL']

/**
 * 기간별로 보기 (예전 '기간별 성장 리포트' 화면을 합침): 기간 고르고 → 그 기간 리포트 화면으로.
 * 학습 시간·약점 순위·아트메이트 설명은 리포트 화면에서. 지난 리포트는 접어 둠
 */
function PeriodReport() {
  const navigate = useNavigate()
  const load = useCallback(() => listReports(), [])
  const { data } = useAsync(load)
  const [period, setPeriod] = useState('MONTH')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const past = data?.items ?? []

  async function open() {
    setBusy(true)
    setError('')
    try {
      const report = await createReport({ period, includeAi: false })
      navigate(`/growth/reports/${report.id}`)
    } catch (err) {
      setError(toErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <section className={styles.periodBox}>
      <div className={styles.periodHead}>
        <img src={MASCOT_POSES.growth} alt="" className={styles.periodCat} />
        <h2 className={styles.periodTitle}>기간별로 성장 리포트 보기</h2>
      </div>
      <div className={styles.periodRow}>
        <div className={styles.periods} role="radiogroup" aria-label="기간">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={period === p}
              className={styles.period}
              onClick={() => setPeriod(p)}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
        <button type="button" className={styles.periodGo} onClick={open} disabled={busy}>
          {busy ? '만드는 중…' : '보기'}
        </button>
      </div>
      {error && <p className={styles.error}>{error}</p>}
      {past.length > 0 && (
        <>
          <p className={styles.pastHead}>지난 리포트</p>
          {/* 기간을 작은 날짜 칩으로 줄줄이 (최근 12개). 누르면 그 리포트 */}
          <ul className={styles.pastChips}>
            {past.slice(0, 12).map((r) => (
              <li key={r.id}>
                <Link
                  to={`/growth/reports/${r.id}`}
                  className={`${styles.pastChip} ${r.status === 'INSUFFICIENT_DATA' ? styles.pastThin : ''}`}
                  title={PERIOD_LABELS[r.period_type]}
                >
                  {r.period_start
                    ? `${dot(r.period_start)}~${dot(r.period_end)}`
                    : `~${dot(r.period_end)}`}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

/** "2026-11-25" → "11.25" */
const dot = (iso) => {
  const [, m, d] = iso.split('-').map(Number)
  return `${m}.${d}`
}

// 섹션 색: 뜻으로 나눔 (지적 분홍 · 칭찬 초록 · 좋아짐 하늘 · 보완 노랑 · 나머지 주황/보라)
const TONE = {
  base: '#f2933a',
  recent: '#a99ff0',
  issue: '#f29bb0',
  good: '#9fb34a',
  up: '#6fb8dc',
  todo: '#e9b949',
}

/**
 * 한눈에 보기: 잘하는 점(웃는 고양이) → 좋아지는 점(응원 고양이) → 보완할 점(붓 든 고양이),
 * 각각 짧은 문장 3개까지 (칭찬 먼저)
 * 문장은 서버가 준 영역 이름·작품 수로만 만듦 (해석 덧붙이지 않음). 누르면 그 섹션으로
 */
function Glance({ report }) {
  const groups = [
    {
      id: 'report-strengths',
      icon: ThumbsUp,
      cat: 'happy',
      title: '잘하고 있어요!',
      tone: TONE.good,
      tags: report.strengths,
      line: () => '칭찬을 여러 번 받았어요',
      empty: '작품이 더 쌓이면 잘하는 점을 찾아 드릴게요!',
    },
    {
      id: 'report-improving',
      icon: Sprout,
      cat: 'cheer',
      title: '점점 좋아지고 있어요!',
      tone: TONE.up,
      tags: report.improving,
      line: (t) =>
        t.improvement_confirmed
          ? '지적받은 뒤 계속 칭찬받고 있어요'
          : '지적받은 뒤 칭찬으로 바뀌었어요',
      empty: '지적받은 부분이 칭찬으로 바뀌면 알려 드릴게요',
    },
    {
      id: 'report-needs',
      icon: Target,
      cat: 'artist',
      title: '이것만 보완하면 더 좋아져요',
      tone: TONE.issue,
      tags: report.needs_work,
      line: (t) =>
        t.issue_artwork_count >= 2
          ? '조금만 더 신경 쓰면 좋아져요'
          : '최근 첨삭에서 한 번 더 짚어 줬어요',
      empty: '지금은 보완할 부분이 없어요. 아주 좋아요!',
    },
  ]
  return (
    <div className={styles.glance}>
      {groups.map(({ id, cat, title, tone, line, tags, empty }) => (
        <a key={id} href={`#${id}`} className={styles.glanceRow} style={{ '--tone': tone }}>
          <img src={MASCOT_POSES[cat]} alt="" className={styles.glanceCat} />
          <span className={styles.glanceText}>
            <span className={styles.glanceTitle}>{title}</span>
            {tags.length ? (
              <ul className={styles.glanceLines}>
                {tags.slice(0, 3).map((t) => (
                  <li key={t.tag}>
                    <mark className={styles.hl}>{t.label}</mark> {line(t)}
                  </li>
                ))}
              </ul>
            ) : (
              <span className={styles.glanceEmpty}>{empty}</span>
            )}
          </span>
          <ChevronRight size={16} className={styles.glanceChevron} aria-hidden />
        </a>
      ))}
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
  if (!items.length) return <p className={styles.muted}>아직 정리된 첨삭이 없어요.</p>
  return (
    <ul className={styles.recent}>
      {items.map((f, i) => (
        <RecentFeedback key={f.feedback_id} feedback={f} defaultOpen={i === 0} />
      ))}
    </ul>
  )
}

/**
 * 최근 첨삭 하나 = 접고 펴는 줄. 머리(작품 · 날짜 · ⌄)를 누르면 요약 문장·분류·첨삭 보기가 펼쳐짐.
 * 가장 최근 것만 처음에 펼쳐 둠. 글자는 그대로, 문장마다 줄만 나눔
 */
function RecentFeedback({ feedback: f, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <li className={styles.recentItem}>
      <button
        type="button"
        className={styles.recentHead}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <DateBadge date={f.work_date} />
        <span className={styles.recentText}>
          <span className={styles.recentTitle}>{f.artwork_title}</span>
          {!open && <span className={styles.recentPeek}>{splitSentences(f.summary)[0]}</span>}
        </span>
        <ChevronDown size={16} aria-hidden className={open ? styles.chevronUp : styles.chevron} />
      </button>
      {open && (
        <div className={styles.recentBody}>
          <ul className={styles.sentences}>
            {splitSentences(f.summary).map((sentence, i) => (
              <li key={i}>{sentence}</li>
            ))}
          </ul>
          <div className={styles.recentFoot}>
            {f.tags.length > 0 && (
              <div className={styles.chips}>
                {f.tags.map((tag) => (
                  <span key={tag} className={styles.chip}>
                    {TAG_LABELS[tag] ?? tag}
                  </span>
                ))}
              </div>
            )}
            <Link to={`/feedbacks/${f.feedback_id}`} className={styles.textLink}>
              첨삭 보기 <ChevronRight size={12} aria-hidden />
            </Link>
          </div>
        </div>
      )}
    </li>
  )
}

/** 달력 한 장처럼: 위에 '11월', 아래 큰 '16' */
function DateBadge({ date }) {
  const [, month, day] = date.split('-').map(Number)
  return (
    <span className={styles.dateBadge} aria-label={formatMonthDay(date)}>
      <span className={styles.dateMonth}>{month}월</span>
      <span className={styles.dateDay}>{day}</span>
    </span>
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

/** 섹션 카드: 색 동그라미 아이콘(또는 고양이) + 제목 → 내용. 색은 섹션 뜻(TONE) */
function Section({ id, icon: Icon, cat, title, tone, children }) {
  return (
    <section
      id={id}
      className={`${styles.section} ${cat ? styles.withCat : ''}`}
      style={{ '--tone': tone }}
    >
      {/* 고양이는 카드 안에 넣지 않고 카드 위 모서리에 걸터앉게 (오른쪽 위) */}
      {cat && (
        <img
          src={MASCOT_POSES[cat]}
          alt=""
          className={`${styles.sectionCat} ${cat === 'good' ? styles.sectionCatBig : ''}`}
        />
      )}
      <header className={styles.sectionHead}>
        {Icon && (
          <span className={styles.sectionIcon} aria-hidden>
            <Icon size={16} />
          </span>
        )}
        <h2 className={styles.sectionTitle}>{title}</h2>
      </header>
      {children}
    </section>
  )
}

/** 물감 점 숫자 타일 (홈 학습 현황과 같은 모양) */

import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Badge, Card } from '../../../components/ui'
import { TREND_LABELS } from '../labels'
import EvidenceList from './EvidenceList'
import Notes from './Notes'
import styles from './WeaknessAnalysis.module.css'

/**
 * 반복 약점 분석 (GET /growth/me/weaknesses, 리포트의 statistics 공통 형태)
 * 승인된 강사 첨삭만 집계 · 자기 메모/다른 학생 의견은 unverified_mentions로 따로
 */
export default function WeaknessAnalysis({ analysis }) {
  const { totals } = analysis

  if (analysis.status === 'INSUFFICIENT_DATA') {
    return (
      <div className={styles.wrap}>
        <Card variant="soft" className={styles.empty}>
          <p className={styles.emptyTitle}>
            {analysis.message ?? '분석에 필요한 기록이 부족해요.'}
          </p>
          <p>
            확정된 첨삭이 있는 작품 {totals.analyzed_artwork_count}개 / 필요{' '}
            {analysis.required_artwork_count}개
          </p>
          {analysis.guidance?.map((line) => (
            <p key={line} className={styles.guidance}>
              {line}
            </p>
          ))}
        </Card>
        <TimeStats stats={analysis.time_stats} />
        <Notes notes={analysis.notes} />
      </div>
    )
  }

  const byCategory = Object.fromEntries(analysis.weaknesses.map((w) => [w.category, w]))
  const top = analysis.top_weaknesses.map((c) => byCategory[c]).filter(Boolean)
  const others = analysis.weaknesses.filter((w) => !analysis.top_weaknesses.includes(w.category))

  return (
    <div className={styles.wrap}>
      <Card variant="dark" className={styles.totals}>
        <Stat value={totals.artwork_count} label="총 작품" />
        <Stat value={totals.analyzed_artwork_count} label="분석한 작품" />
        <Stat value={totals.approved_feedback_count} label="확정 첨삭" />
      </Card>
      {analysis.confidence === 'LOW' && <Badge>기록이 적어 참고용이에요</Badge>}

      {top.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.heading}>반복해서 지적된 약점</h2>
          {top.map((weakness, i) => (
            <WeaknessCard
              key={weakness.category}
              weakness={weakness}
              rank={i + 1}
              analyzed={totals.analyzed_artwork_count}
            />
          ))}
        </section>
      )}

      {others.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.heading}>그 밖에 지적된 약점</h2>
          {others.map((weakness) => (
            <WeaknessCard
              key={weakness.category}
              weakness={weakness}
              analyzed={totals.analyzed_artwork_count}
            />
          ))}
        </section>
      )}

      {analysis.strengths?.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.heading}>긍정적으로 언급된 부분</h2>
          <div className={styles.chips}>
            {analysis.strengths.map((s) => (
              <span key={s.category} className={styles.strength}>
                {s.label} · 작품 {s.artwork_count}개
              </span>
            ))}
          </div>
        </section>
      )}

      {analysis.next_goals?.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.heading}>다음 연습 목표</h2>
          <ul className={styles.goals}>
            {analysis.next_goals.map((goal) => (
              <li key={goal.category}>{goal.goal}</li>
            ))}
          </ul>
        </section>
      )}

      {analysis.unverified_mentions?.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.heading}>자기 메모·다른 학생 의견 (참고용)</h2>
          <p className={styles.caption}>강사 첨삭이 아니라서 반복 약점 분석에는 넣지 않았어요.</p>
          <div className={styles.chips}>
            {analysis.unverified_mentions.map((m) => (
              <span key={m.category} className={styles.unverified}>
                {m.label} · {m.mention_count}번
              </span>
            ))}
          </div>
        </section>
      )}

      <TimeStats stats={analysis.time_stats} />
      <Notes notes={analysis.notes} />
    </div>
  )
}

function WeaknessCard({ weakness, rank, analyzed }) {
  const [open, setOpen] = useState(false)
  return (
    <Card className={styles.weakness}>
      <button
        type="button"
        className={styles.weaknessHeader}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {rank && <span className={styles.rank}>{rank}</span>}
        <span className={styles.weaknessText}>
          <span className={styles.weaknessTitle}>{weakness.label}</span>
          <span className={styles.weaknessSub}>
            작품 {analyzed}개 중 {weakness.artwork_count}개에서 지적 ·{' '}
            {TREND_LABELS[weakness.trend] ?? ''}
          </span>
        </span>
        {open ? <ChevronUp size={20} aria-hidden /> : <ChevronDown size={20} aria-hidden />}
      </button>
      {open && <EvidenceList evidence={weakness.evidence} />}
    </Card>
  )
}

function TimeStats({ stats }) {
  if (!stats?.recorded_artwork_count) return null
  const mock = stats.mock_exam
  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>학습 시간</h2>
      <Card className={styles.timeCard}>
        <p>
          시간을 기록한 작품 {stats.recorded_artwork_count}개 · 총{' '}
          {formatMinutes(stats.total_minutes)} · 평균{' '}
          {formatMinutes(Math.round(stats.average_minutes))}
        </p>
        {mock?.timed_count > 0 && (
          <p className={styles.caption}>
            모의시험 {mock.artwork_count}개 중 시간 기록 {mock.timed_count}개 · 제한 시간 초과{' '}
            {mock.over_limit_count}개
          </p>
        )}
      </Card>
    </section>
  )
}

function formatMinutes(minutes) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}시간${m ? ` ${m}분` : ''}` : `${m}분`
}

function Stat({ value, label }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}

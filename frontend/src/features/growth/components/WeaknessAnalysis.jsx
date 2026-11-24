import { useState } from 'react'
import { ChevronDown, Clock, NotebookPen, Palette } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MASCOT_POSES } from '../../../components/mascot/poses'
import { formatMonthDay } from '../../../utils/date'
import { josa } from '../insightsView'
import Notes from './Notes'
import styles from './WeaknessAnalysis.module.css'

// 최근 흐름을 쉬운 말로 (서버 trend 값 그대로 바꿔 부르기만)
const TREND_TEXT = {
  MORE_FREQUENT: '요즘 더 자주 나와요',
  LESS_FREQUENT: '점점 덜 나와요',
  SIMILAR: '요즘도 가끔 나와요',
}

/**
 * 기간 성장 리포트 본문 (리포트의 statistics). 숫자는 서버 값 그대로, 말투만 쉽게.
 * 순서: 이 기간 기록(작품·첨삭·시간) → 잘하고 있어요 → 보완하면 좋아져요 → 다음 목표 → 참고 의견
 * 승인된 강사 첨삭만 집계 · 자기 메모/다른 학생 의견은 unverified_mentions로 따로 (접어 둠)
 */
export default function WeaknessAnalysis({ analysis }) {
  const { totals } = analysis
  const time = analysis.time_stats

  const record = (
    <div className={styles.stats}>
      <Stat icon={Palette} value={`${totals.artwork_count}점`} label="그린 작품" />
      <Stat
        icon={NotebookPen}
        value={`${totals.analyzed_artwork_count}점`}
        label="첨삭 받은 작품"
      />
      <Stat
        icon={Clock}
        value={time?.recorded_artwork_count ? formatMinutes(time.total_minutes) : '–'}
        label="그린 시간"
      />
    </div>
  )

  if (analysis.status === 'INSUFFICIENT_DATA') {
    return (
      <div className={styles.wrap}>
        {record}
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>
            {analysis.message ?? '첨삭 받은 작품이 조금 더 쌓이면 분석해 드릴게요.'}
          </p>
          {analysis.guidance?.map((line) => (
            <p key={line} className={styles.muted}>
              {line}
            </p>
          ))}
        </div>
        <Notes notes={analysis.notes} />
      </div>
    )
  }

  const byCategory = Object.fromEntries(analysis.weaknesses.map((w) => [w.category, w]))
  const top = analysis.top_weaknesses.map((c) => byCategory[c]).filter(Boolean)
  const others = analysis.weaknesses.filter((w) => !analysis.top_weaknesses.includes(w.category))
  const weaknesses = [...top, ...others]
  const mock = time?.mock_exam
  const labelByCategory = Object.fromEntries(
    [...analysis.weaknesses, ...(analysis.strengths ?? [])].map((w) => [w.category, w.label]),
  )

  return (
    <div className={styles.wrap}>
      {record}
      {mock?.timed_count > 0 && (
        <p className={styles.note}>
          실기시험 {mock.artwork_count}번 중 {mock.timed_count}번 시간을 쟀고, 제한 시간을 넘긴 건{' '}
          {mock.over_limit_count}번이에요.
        </p>
      )}
      {analysis.confidence === 'LOW' && (
        <p className={styles.note}>기록이 아직 적어서 참고로만 봐 주세요.</p>
      )}

      {analysis.strengths?.length > 0 && (
        <TalkSection
          tone="#9fb34a"
          pose="happy"
          title="잘하고 있어요!"
          hint="어떤 걸 잘했는지 눌러 봐요"
          items={analysis.strengths}
          ask={(s) =>
            s.category === 'OTHER' ? '그 밖에 잘한 건?' : `${josa(s.label, '은', '는')} 어땠어?`
          }
          reply={(s, found) =>
            found ? '선생님이 이렇게 칭찬했어요!' : '칭찬 문장을 찾지 못했어요.'
          }
        />
      )}

      {weaknesses.length > 0 && (
        <TalkSection
          right
          tone="#f29bb0"
          pose="artist"
          title="이것만 보완하면 더 좋아져요"
          hint="무엇을 다듬으면 좋을지 눌러 봐요"
          items={weaknesses}
          ask={(w) =>
            w.category === 'OTHER'
              ? '그 밖에 다듬을 건?'
              : `${josa(w.label, '은', '는')} 어떻게 해?`
          }
          reply={(w, found) =>
            found ? '선생님이 이렇게 짚어 줬어요!' : '선생님 말을 찾지 못했어요.'
          }
          note={(w) => TREND_TEXT[w.trend]}
        />
      )}

      {analysis.next_goals?.length > 0 && (
        // '다음 목표!' 판을 가리키는 고양이가 제목 대신, 그 아래 카드에 목표 목록
        <section className={styles.goalSection} aria-label="다음 목표">
          <img src={MASCOT_POSES.goal} alt="" className={styles.goalCat} />
          <ul className={styles.goals}>
            {analysis.next_goals.map((goal) => (
              <GoalMission key={goal.category} goal={goal} label={labelByCategory[goal.category]} />
            ))}
          </ul>
        </section>
      )}

      {analysis.unverified_mentions?.length > 0 && (
        <details className={styles.unverified}>
          <summary>
            자기 메모·친구 의견 (참고) <ChevronDown size={14} aria-hidden />
          </summary>
          <p className={styles.muted}>선생님 첨삭이 아니라서 위 분석에는 넣지 않았어요.</p>
          <div className={styles.chips}>
            {analysis.unverified_mentions.map((m) => (
              <span key={m.category} className={styles.plainChip}>
                {m.label}
              </span>
            ))}
          </div>
        </details>
      )}

      <Notes notes={analysis.notes} />
    </div>
  )
}

/**
 * 고양이와 채팅하는 섹션 (잘하고 있어요 · 보완하면 좋아져요 공용, 카드 없음).
 * 맨 위: 고양이 + 큰 말풍선(title). 그 아래 영역 칩을 고르면
 * 내 말풍선(ask) → 고양이 답(reply, note) → 선생님 문장 말풍선들(출처: 작품 · 날짜 첨삭에서).
 * right: 고양이를 오른쪽에 (말풍선 방향도 반대로). 마지막으로 고른 것만 보여 줌
 */
function TalkSection({ tone, pose, title, hint, items, ask, reply, note, right = false }) {
  const [selected, setSelected] = useState(null)
  const picked = items.find((it) => it.category === selected)
  const quotes = picked?.evidence?.slice(0, 3) ?? []
  const extra = picked && note?.(picked)
  return (
    <section
      className={`${styles.talkSection} ${right ? styles.talkRight : ''}`}
      style={{ '--tone': tone }}
      aria-label={title}
    >
      <div className={styles.talkRow}>
        <img src={MASCOT_POSES[pose]} alt="" className={styles.talkCat} />
        <p className={styles.bigBubble}>{title}</p>
      </div>
      <p className={styles.goodHint}>{hint}</p>
      <div className={styles.chips}>
        {items.map((it) => (
          <button
            key={it.category}
            type="button"
            className={styles.goodChip}
            aria-pressed={selected === it.category}
            onClick={() => setSelected(it.category)}
          >
            {it.label}
          </button>
        ))}
      </div>

      {picked && (
        <div className={styles.chat} key={picked.category} aria-live="polite">
          <p className={styles.me}>{ask(picked)}</p>
          <div className={styles.catSays}>
            <img src={MASCOT_POSES[pose]} alt="" className={styles.avatar} />
            <div className={styles.catBubbles}>
              <p className={styles.catBubble} style={{ '--i': 1 }}>
                {reply(picked, quotes.length > 0)}
                {extra && <span className={styles.quoteSource}>{extra}</span>}
              </p>
              {quotes.map((e, i) => (
                <Link
                  key={e.item_id}
                  to={`/feedbacks/${e.feedback_id}`}
                  className={styles.catBubble}
                  style={{ '--i': i + 2 }}
                >
                  <span>“{e.content}”</span>
                  {e.artwork_title && (
                    <span className={styles.quoteSource}>
                      {e.artwork_title}
                      {e.work_date && ` · ${formatMonthDay(e.work_date)}`} 첨삭에서
                    </span>
                  )}
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

/**
 * 다음 목표 한 개 = 미션 카드. 서버 목표 문장(틀이 같아 딱딱함) 대신 같은 뜻을 쉬운 말로:
 * '색채 미션!' + '스케치할 때부터 색채를 한 번 더 봐요'. 선생님 실제 수정 지시(based_on)가 있으면 아래에 인용.
 * 영역 이름을 모르면 서버 문장 그대로
 */
function GoalMission({ goal, label }) {
  const tip = goal.based_on?.content
  if (!label || goal.category === 'OTHER') {
    return (
      <li className={styles.mission}>
        <span className={styles.missionTitle}>다음 미션!</span>
        <span className={styles.missionText}>{tip ? `“${tip}”` : goal.goal}</span>
      </li>
    )
  }
  return (
    <li className={styles.mission}>
      <span className={styles.missionTitle}>{label} 미션!</span>
      <span className={styles.missionText}>
        스케치할 때부터 {josa(label, '을', '를')} 한 번 더 봐요
      </span>
      {tip && (
        <span className={styles.missionTip}>
          <img src={MASCOT_POSES.teacher} alt="" className={styles.tipCat} />
          <span className={styles.tipBody}>
            <span className={styles.tipWho}>선생님 한마디</span>
            <span className={styles.tipText}>{tip}</span>
          </span>
        </span>
      )}
    </li>
  )
}

function Stat({ icon: Icon, value, label }) {
  return (
    <div className={styles.stat}>
      <Icon size={16} aria-hidden className={styles.statIcon} />
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}

function formatMinutes(minutes) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}시간${m ? ` ${m}분` : ''}` : `${m}분`
}

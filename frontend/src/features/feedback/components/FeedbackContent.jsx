import { Pause, Play } from 'lucide-react'
import { Badge } from '../../../components/ui'
import { labelOf } from '../../../lib/options'
import { ORIGIN_LABELS } from '../feedbackKinds'
import { displayTags } from '../reviewSections'
import styles from '../pages/FeedbackReviewPage.module.css'

/**
 * AI 첨삭 정리 본문 (학생 결과 화면·v1.0 강사 검토 화면 공통):
 * 전체 요약 + 분류 태그 → 잘한 점 → 개선할 점(부족한 점·수정 방법) → [middle] → 다음 작품 연습 과제.
 * player: useEvidencePlayer 결과 (근거 듣기), middle: 화면별 추가 섹션 (학생: 반복 약점)
 */
export default function FeedbackContent({ feedback, options, player, middle = null }) {
  const kindLabel = (kind, fallback) =>
    options ? labelOf(options.feedback_item_kinds, kind) : fallback
  const categoryLabel = (code) => (options ? labelOf(options.weakness_categories, code) : code)
  const tags = displayTags(feedback, categoryLabel)

  const renderItems = (items) =>
    items.length === 0 ? (
      <p className={styles.empty}>언급되지 않음</p>
    ) : (
      <ul className={styles.items}>
        {items.map((item) => (
          <li key={item.id} className={styles.item}>
            <p>{item.content}</p>
            <div className={styles.meta}>
              {item.category && <span className={styles.tag}>{categoryLabel(item.category)}</span>}
              {ORIGIN_LABELS[item.origin] && (
                <span className={styles.origin}>{ORIGIN_LABELS[item.origin]}</span>
              )}
              {player && item.evidence[0]?.start_ms != null && (
                <button
                  type="button"
                  className={styles.listen}
                  onClick={() =>
                    player.play(item.id, item.evidence[0].start_ms, item.evidence.at(-1).end_ms)
                  }
                >
                  {player.playingKey === item.id ? <Pause size={14} /> : <Play size={14} />}
                  근거 듣기
                </button>
              )}
            </div>
            {item.evidence.some((e) => e.text) && (
              <p className={styles.evidence}>
                “
                {item.evidence
                  .map((e) => e.text)
                  .filter(Boolean)
                  .join(' ')}
                ”
              </p>
            )}
          </li>
        ))}
      </ul>
    )

  return (
    <>
      <section className={styles.section}>
        <h2 className={styles.label}>전체 첨삭 요약</h2>
        {feedback.summary ? (
          <p className={styles.summary}>{feedback.summary}</p>
        ) : (
          <p className={styles.empty}>언급되지 않음</p>
        )}
        {tags.length > 0 && (
          <>
            <ul className={styles.chips} aria-label="첨삭 분류">
              {tags.map((tag) => (
                <li key={tag.key}>
                  <Badge className={tag.needsWork ? undefined : styles.tagPraise}>
                    {tag.label}
                    <span className={styles.srOnly}>
                      {tag.needsWork ? ' (개선할 점 있음)' : ' (잘한 점)'}
                    </span>
                  </Badge>
                </li>
              ))}
            </ul>
            {tags.some((t) => !t.needsWork) && tags.some((t) => t.needsWork) && (
              <p className={styles.tagLegend} aria-hidden>
                주황색은 개선할 점이 나온 주제예요.
              </p>
            )}
          </>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.label}>잘한 점</h2>
        {renderItems(feedback.strengths)}
      </section>

      <section className={styles.section}>
        <h2 className={styles.label}>개선할 점</h2>
        {feedback.weaknesses.length === 0 && feedback.fixes.length === 0 ? (
          <p className={styles.empty}>언급되지 않음</p>
        ) : (
          <>
            {feedback.weaknesses.length > 0 && (
              <>
                <h3 className={styles.subLabel}>{kindLabel('WEAKNESS', '부족한 점')}</h3>
                {renderItems(feedback.weaknesses)}
              </>
            )}
            {feedback.fixes.length > 0 && (
              <>
                <h3 className={styles.subLabel}>{kindLabel('FIX', '수정 방법')}</h3>
                {renderItems(feedback.fixes)}
              </>
            )}
          </>
        )}
      </section>

      {middle}

      <section className={styles.section}>
        <h2 className={styles.label}>다음 작품 연습 과제</h2>
        {renderItems(feedback.next_tips)}
      </section>
    </>
  )
}

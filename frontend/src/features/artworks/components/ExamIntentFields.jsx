import { Chip, Input, Textarea } from '../../../components/ui'
import { EXPRESSION_METHODS, PAPER_SIZES, toggleMethod } from '../referencePhotos'
import styles from './ExamIntentFields.module.css'

/**
 * v1.1 시험 조건(선택)·표현 의도(선택) 접는 영역. 입력하지 않아도 작품을 만들 수 있다.
 * methodOptions: /meta/options expression_methods (없으면 기본 목록), showTime: 제한 시간 입력 표시
 */
export default function ExamIntentFields({ value, onChange, methodOptions, showTime = true }) {
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value })
  const methods = methodOptions?.length ? methodOptions : EXPRESSION_METHODS
  const conditionCount = [
    'time_limit_minutes',
    'paper_size',
    'exam_conditions',
    'description',
  ].filter((k) => String(value[k] ?? '').trim()).length
  const intentCount = value.expression_methods.length + (value.expression_intent.trim() ? 1 : 0)

  return (
    <>
      <details className={styles.section} open={conditionCount > 0 || undefined}>
        <summary className={styles.summary}>
          시험 조건{' '}
          <span className={styles.optional}>
            선택{conditionCount ? ` · ${conditionCount}개 입력` : ''}
          </span>
        </summary>
        <div className={styles.content}>
          {showTime && (
            <Input
              label="시험 시간 (분)"
              type="number"
              inputMode="numeric"
              min={1}
              max={1440}
              placeholder="예: 240"
              value={value.time_limit_minutes}
              onChange={set('time_limit_minutes')}
            />
          )}
          <Input
            label="화지 규격"
            maxLength={50}
            placeholder="예: 4절"
            list="artmate-paper-sizes"
            value={value.paper_size}
            onChange={set('paper_size')}
          />
          <datalist id="artmate-paper-sizes">
            {PAPER_SIZES.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <Textarea
            label="추가 시험 조건"
            maxLength={500}
            placeholder="예: 제시물 2개 이상 사용, 배경 표현 필수"
            value={value.exam_conditions}
            onChange={set('exam_conditions')}
          />
          <Textarea
            label="자유 메모"
            maxLength={1000}
            placeholder="기억해 두고 싶은 내용"
            value={value.description}
            onChange={set('description')}
          />
        </div>
      </details>

      <details className={styles.section} open={intentCount > 0 || undefined}>
        <summary className={styles.summary}>
          표현 의도 <span className={styles.optional}>선택{intentCount ? ' · 입력함' : ''}</span>
        </summary>
        <div className={styles.content}>
          <div className={styles.field}>
            <span className={styles.label} id="expression-methods-label">
              표현 방식 (여러 개 선택)
            </span>
            <div className={styles.chips} role="group" aria-labelledby="expression-methods-label">
              {methods.map((m) => (
                <Chip
                  key={m.code}
                  selected={value.expression_methods.includes(m.code)}
                  onClick={() =>
                    onChange({
                      ...value,
                      expression_methods: toggleMethod(value.expression_methods, m.code),
                    })
                  }
                >
                  {m.label}
                </Chip>
              ))}
            </div>
          </div>
          <Textarea
            label="의도 설명"
            maxLength={1000}
            placeholder="예: 유리컵을 기울여 역동적인 구도를 만들고 싶었어요."
            value={value.expression_intent}
            onChange={set('expression_intent')}
          />
          <p className={styles.note}>
            적은 의도는 나중에 AI 비교 첨삭에서 참고해요. 비워 두면 AI가 의도를 짐작하지 않아요.
          </p>
        </div>
      </details>
    </>
  )
}

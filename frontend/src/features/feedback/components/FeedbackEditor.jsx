import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Chip, Textarea } from '../../../components/ui'
import { labelOf } from '../../../lib/options'
import { KINDS } from '../feedbackKinds'
import styles from './FeedbackEditor.module.css'

let tempId = 0
const newKey = () => `new-${++tempId}`

/** 첨삭 전체 수정. onSave({ summary, items, categories })로 PATCH 본문을 넘김 */
export default function FeedbackEditor({ feedback, options, saving, onSave, onCancel }) {
  const [summary, setSummary] = useState(feedback.summary)
  const [items, setItems] = useState(() =>
    KINDS.flatMap(({ field }) =>
      feedback[field].map((item) => ({
        key: item.id,
        id: item.id,
        kind: item.kind,
        content: item.content,
        category: item.category,
      })),
    ),
  )
  const [categories, setCategories] = useState(feedback.categories)
  const weaknessOptions = options?.weakness_categories ?? []

  const update = (key, patch) =>
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, ...patch } : item)))
  const remove = (key) => setItems((prev) => prev.filter((item) => item.key !== key))
  const add = (kind) =>
    setItems((prev) => [...prev, { key: newKey(), id: undefined, kind, content: '', category: null }])
  const toggleCategory = (code) =>
    setCategories((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]))

  const filled = items.filter((item) => item.content.trim())
  const canSave = summary.trim() && !saving

  function handleSave() {
    onSave({
      summary: summary.trim(),
      // 내용이 빈 항목은 보내지 않음 (= 삭제)
      items: filled.map(({ id, kind, content, category }) => ({
        ...(id ? { id } : {}),
        kind,
        content: content.trim(),
        category: category || null,
      })),
      categories,
    })
  }

  return (
    <div className={styles.editor}>
      <Textarea
        label="핵심 요약"
        value={summary}
        maxLength={1000}
        onChange={(e) => setSummary(e.target.value)}
      />

      {KINDS.map(({ kind, label }) => {
        const kindLabel = options ? labelOf(options.feedback_item_kinds, kind) : label
        return (
          <section key={kind} className={styles.section}>
            <h3 className={styles.heading}>{kindLabel}</h3>
            {items
              .filter((item) => item.kind === kind)
              .map((item) => (
                <div key={item.key} className={styles.item}>
                  <Textarea
                    aria-label={kindLabel}
                    rows={2}
                    maxLength={500}
                    value={item.content}
                    onChange={(e) => update(item.key, { content: e.target.value })}
                  />
                  <div className={styles.itemRow}>
                    <select
                      className={styles.select}
                      value={item.category ?? ''}
                      onChange={(e) => update(item.key, { category: e.target.value || null })}
                      aria-label="약점 카테고리"
                    >
                      <option value="">카테고리 없음</option>
                      {weaknessOptions.map((o) => (
                        <option key={o.code} value={o.code}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className={styles.remove}
                      onClick={() => remove(item.key)}
                      aria-label="항목 삭제"
                    >
                      <Trash2 size={18} />
                    </button>
                  </div>
                </div>
              ))}
            <button type="button" className={styles.add} onClick={() => add(kind)}>
              <Plus size={16} aria-hidden />
              항목 추가
            </button>
          </section>
        )
      })}

      <section className={styles.section}>
        <h3 className={styles.heading}>약점 카테고리</h3>
        <div className={styles.chips}>
          {weaknessOptions.map((o) => (
            <Chip key={o.code} selected={categories.includes(o.code)} onClick={() => toggleCategory(o.code)}>
              {o.label}
            </Chip>
          ))}
        </div>
      </section>

      <div className={styles.actions}>
        <Button onClick={handleSave} disabled={!canSave}>
          {saving ? '저장하는 중…' : '저장하기'}
        </Button>
        <Button variant="soft" onClick={onCancel} disabled={saving}>
          취소
        </Button>
      </div>
    </div>
  )
}

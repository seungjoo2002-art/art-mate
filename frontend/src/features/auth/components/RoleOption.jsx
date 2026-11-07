import { IconBox } from '../../../components/ui'
import { ROLES } from '../roles'
import styles from './RoleOption.module.css'

/** 학생/강사 선택 카드 (radiogroup 안에서 사용) */
export default function RoleOption({ role, selected, onSelect }) {
  const { eyebrow, title, description, icon, iconVariant } = ROLES[role]

  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      className={`${styles.option} ${selected ? styles.selected : ''}`}
      onClick={() => onSelect(role)}
    >
      <IconBox icon={icon} variant={iconVariant} size="lg" />
      <span className={styles.text}>
        <span className={styles.eyebrow}>{eyebrow}</span>
        <span className={styles.title}>{title}</span>
        <span className={styles.description}>{description}</span>
      </span>
      <span className={styles.radio} aria-hidden />
    </button>
  )
}

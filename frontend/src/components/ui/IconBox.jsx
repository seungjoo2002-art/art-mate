import styles from './IconBox.module.css'

/** 둥근 사각형 안의 아이콘. variant: soft(크림) | dark(갈색) | muted(회색) */
export default function IconBox({ icon: Icon, variant = 'soft', size = 'md', className = '' }) {
  return (
    <span className={`${styles.box} ${styles[variant]} ${styles[size]} ${className}`} aria-hidden>
      <Icon size={size === 'lg' ? 32 : 22} />
    </span>
  )
}

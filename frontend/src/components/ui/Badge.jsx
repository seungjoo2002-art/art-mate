import styles from './Badge.module.css'

/** 작은 라벨. variant: soft(크림) | overlay(사진 위 반투명) | light(어두운 카드 위) */
export default function Badge({ variant = 'soft', className = '', ...props }) {
  return <span className={`${styles.badge} ${styles[variant]} ${className}`} {...props} />
}

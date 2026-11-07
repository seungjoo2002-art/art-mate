import styles from './Card.module.css'

/** variant: default(흰색) | dark(갈색 강조) | soft(크림색 안내) */
export default function Card({ as: Tag = 'div', variant = 'default', className = '', ...props }) {
  return <Tag className={`${styles.card} ${styles[variant]} ${className}`} {...props} />
}

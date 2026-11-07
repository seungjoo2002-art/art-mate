import { ChevronRight } from 'lucide-react'
import styles from './Button.module.css'

/**
 * variant: primary(주황) | dark(갈색) | soft(연한 회색)
 * size: lg(하단 CTA, 56px) | md(카드 안, 48px)
 */
export default function Button({
  variant = 'primary',
  size = 'lg',
  fullWidth = true,
  withArrow = false,
  className = '',
  children,
  ...props
}) {
  const classes = [
    styles.button,
    styles[variant],
    styles[size],
    fullWidth && styles.fullWidth,
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button type="button" className={classes} {...props}>
      {children}
      {withArrow && <ChevronRight size={22} strokeWidth={2.5} aria-hidden />}
    </button>
  )
}

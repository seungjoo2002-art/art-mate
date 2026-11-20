import { ChevronRight } from 'lucide-react'
import styles from './Button.module.css'

/**
 * variant: primary(주황) | dark(갈색) | soft(연한 회색)
 * size: lg(56px) | md(카드 안, 48px) | compact(화면 주 버튼: 48px 알약, 가운데, 글자 길이만큼·최소 200px)
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
    fullWidth && size !== 'compact' && styles.fullWidth,
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

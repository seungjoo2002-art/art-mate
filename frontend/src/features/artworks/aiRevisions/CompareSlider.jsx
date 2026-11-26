import { useRef, useState } from 'react'
import { ChevronsLeftRight } from 'lucide-react'
import { clampPercent, percentAt } from './revisionView'
import styles from './CompareSlider.module.css'

/**
 * 원본 / AI 수정작 Before·After 비교 (같은 자리에 겹쳐 놓고 가운데 손잡이로 나눔).
 * - 상자 비율 = 원본 비율 → 원본은 잘리거나 늘어나지 않음. AI 수정작 비율이 다르면 늘리지 않고
 *   같은 상자 안에 contain으로 맞춤 (구도가 달라도 왜곡하지 않음).
 * - 손가락: 상자 안 가로 움직임은 비교 손잡이가 가져가고(touch-action: pan-y) 세로 스크롤은 그대로.
 *   pointer 이벤트를 위로 보내지 않아 사진 가로 슬라이드가 넘어가지 않음.
 * - PC: 마우스 끌기·클릭, 키보드 ←/→(5%)·Home/End.
 * originalSrc·revisionSrc: 이미지 주소, ratio: 원본 가로/세로 (모르면 사진을 불러온 뒤 계산)
 * onDraggingChange(bool): 조작 중 상위 슬라이드 잠금용
 */
export default function CompareSlider({
  originalSrc,
  revisionSrc,
  ratio: initialRatio,
  onDraggingChange,
  onOriginalError,
  onRevisionError,
  initial = 50,
}) {
  const box = useRef(null)
  const [position, setPosition] = useState(initial)
  const [ratio, setRatio] = useState(initialRatio || null)
  const dragging = useRef(false)

  function move(e) {
    setPosition(percentAt(e.clientX, box.current.getBoundingClientRect()))
  }

  function handlePointerDown(e) {
    e.stopPropagation()
    if (e.pointerType === 'mouse' && e.button !== 0) return
    dragging.current = true
    box.current.setPointerCapture?.(e.pointerId)
    onDraggingChange?.(true)
    move(e)
  }
  function handlePointerMove(e) {
    e.stopPropagation()
    if (dragging.current) move(e)
  }
  function end(e) {
    e.stopPropagation()
    if (!dragging.current) return
    dragging.current = false
    box.current.releasePointerCapture?.(e.pointerId)
    onDraggingChange?.(false)
  }

  function handleKeyDown(e) {
    const step = { ArrowLeft: -5, ArrowRight: 5 }[e.key]
    if (step !== undefined) setPosition((p) => clampPercent(p + step))
    else if (e.key === 'Home') setPosition(0)
    else if (e.key === 'End') setPosition(100)
    else return
    e.preventDefault()
    e.stopPropagation() // 사진 슬라이드의 ←/→로 가지 않게
  }

  return (
    <div
      ref={box}
      className={styles.compare}
      style={ratio ? { '--ratio': ratio } : undefined}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onClick={(e) => e.stopPropagation()}
    >
      <img
        src={originalSrc}
        alt="원본 작품"
        className={styles.image}
        draggable={false}
        onError={onOriginalError}
        onLoad={(e) => {
          const { naturalWidth: w, naturalHeight: h } = e.currentTarget
          if (w && h) setRatio(w / h)
        }}
      />
      <div className={styles.after} style={{ clipPath: `inset(0 0 0 ${position}%)` }}>
        <img
          src={revisionSrc}
          alt="AI 수정 예시"
          className={styles.image}
          draggable={false}
          onError={onRevisionError}
        />
      </div>
      <span className={`${styles.label} ${styles.left}`} aria-hidden>
        원본
      </span>
      <span className={`${styles.label} ${styles.right}`} aria-hidden>
        AI 수정작
      </span>
      <div className={styles.divider} style={{ left: `${position}%` }}>
        <span
          className={styles.handle}
          role="slider"
          tabIndex={0}
          aria-label="원본과 AI 수정작 비교 위치"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(position)}
          aria-valuetext={`왼쪽 원본 ${Math.round(position)}%`}
          onKeyDown={handleKeyDown}
        >
          <ChevronsLeftRight size={18} aria-hidden />
        </span>
      </div>
    </div>
  )
}

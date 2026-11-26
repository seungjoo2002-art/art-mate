import { useEffect, useRef } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import ArtworkPhoto from './ArtworkPhoto'
import styles from './PhotoCarousel.module.css'

const DRAG_CLICK_PX = 6 // 이만큼 넘게 끌면 클릭(확대 보기)으로 보지 않음
const SCROLL_QUIET_MS = 300 // 스크롤이 멈춘 지 이만큼 안 됐으면 누름을 확대 보기로 보지 않음

/**
 * 단계 사진 가로 슬라이드: 한 번에 한 장, 좌우로 넘김. 사진은 원래 비율 그대로 (잘리지 않게 contain).
 * 모바일은 손가락 스와이프(scroll-snap), PC는 좌우 화살표·마우스 끌기·키보드 ←/→.
 * 사진이 1장이면 화살표·표시 없이 사진만.
 * photos: 순서대로, index: 지금 보는 사진, onIndexChange(i), onOpen(photo): 사진을 누르면 (확대 보기)
 * (v1.3, 선택) renderSlide(photo, i): 칸 안 내용을 바꿈 (AI 수정본 화면의 원본·비교·수정작)
 *   canOpen(photo, i): false면 그 칸은 누를 수 있는 버튼이 아님 (비교 슬라이더처럼 칸 안에서 조작)
 *   locked: true인 동안 가로로 넘어가지 않음 (비교 손잡이 조작 중), className: 칸 높이 등 화면별 조정
 */
export default function PhotoCarousel({
  artworkId,
  photos,
  index,
  onIndexChange,
  alt,
  onOpen,
  renderSlide,
  canOpen,
  locked = false,
  className = '',
}) {
  const track = useRef(null)
  const drag = useRef(null) // PC 마우스 끌기
  const press = useRef(null) // 손가락·마우스 누름 (확대 보기를 열어도 되는 누름인지)
  const lastScroll = useRef(-Infinity) // 마지막 스크롤 이벤트 시각 (event.timeStamp)
  // 코드로 옮기는 중인 목표 칸: 부드럽게 넘어가는 동안 지나가는 칸을 '선택'으로 알리지 않음
  // (주소의 ?photo=로 두 번째 이후 사진을 열 때 첫 사진으로 되돌아가던 문제)
  const target = useRef(null)
  const placed = useRef(false) // 처음 자리 잡기는 애니메이션 없이
  const many = photos.length > 1
  const current = Math.min(Math.max(index, 0), photos.length - 1)

  // 밖에서 index가 바뀌면(사진 추가·삭제, 표시 점 누르기) 그 사진으로 이동
  useEffect(() => {
    const el = track.current
    if (!el || !el.clientWidth) return
    if (Math.round(el.scrollLeft / el.clientWidth) !== current) {
      target.current = current
      el.scrollTo({
        left: current * el.clientWidth,
        behavior: placed.current ? 'smooth' : 'instant',
      })
    }
    placed.current = true
  }, [current, photos.length])

  function handleScroll(e) {
    lastScroll.current = e.timeStamp
    const el = track.current
    if (!el || !el.clientWidth || drag.current?.active) return
    const next = Math.round(el.scrollLeft / el.clientWidth)
    if (target.current !== null) {
      if (next === target.current) target.current = null
      return
    }
    if (next !== current && next >= 0 && next < photos.length) onIndexChange(next)
  }

  const go = (i) => onIndexChange(Math.min(Math.max(i, 0), photos.length - 1))

  // 누름 기록: 손가락이 조금이라도 움직였거나 브라우저가 스크롤로 가져가면(pointercancel) 확대 보기 안 함
  // PC 마우스 끌기는 직접 넘김 (터치 스와이프·세로 스크롤은 브라우저에 맡김)
  function handlePointerDown(e) {
    press.current = { x: e.clientX, y: e.clientY, moved: false }
    target.current = null // 사용자가 직접 넘기기 시작하면 코드 이동은 끝난 것으로
    if (locked) return
    if (!many || e.pointerType !== 'mouse' || e.button !== 0) return
    drag.current = { x: e.clientX, left: track.current.scrollLeft, moved: 0, active: true }
  }
  function handlePointerMove(e) {
    const p = press.current
    if (p && Math.hypot(e.clientX - p.x, e.clientY - p.y) > DRAG_CLICK_PX) p.moved = true
    const d = drag.current
    if (!d?.active) return
    const dx = e.clientX - d.x
    d.moved = Math.max(d.moved, Math.abs(dx))
    if (d.moved > DRAG_CLICK_PX) {
      track.current.classList.add(styles.dragging)
      track.current.scrollLeft = d.left - dx
    }
  }
  function handlePointerUp(e) {
    const d = drag.current
    if (!d?.active) return
    d.active = false
    track.current.classList.remove(styles.dragging)
    if (d.moved > DRAG_CLICK_PX) {
      const dx = e.clientX - d.x
      const width = track.current.clientWidth
      // 조금만 끌어도 넘어가게 (폭의 15%)
      const step = Math.abs(dx) > width * 0.15 ? (dx < 0 ? 1 : -1) : 0
      const target = Math.min(Math.max(current + step, 0), photos.length - 1)
      track.current.scrollTo({ left: target * width, behavior: 'smooth' })
      if (target !== current) onIndexChange(target)
    }
  }

  function handlePointerCancel() {
    if (press.current) press.current.moved = true
  }

  function handleClick(photo, e) {
    const moved = press.current?.moved || (drag.current?.moved ?? 0) > DRAG_CLICK_PX
    const scrolling = e.timeStamp - lastScroll.current < SCROLL_QUIET_MS
    press.current = null
    drag.current = null
    // 키보드(Enter·Space)로 누른 것은 detail 0 → 바로 열기
    if (e.detail !== 0 && (moved || scrolling)) return
    onOpen?.(photo)
  }

  function handleKeyDown(e) {
    if (!many) return
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      go(current - 1)
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      go(current + 1)
    }
  }

  if (!photos.length) return null

  return (
    <div className={`${styles.carousel} ${className}`}>
      <div className={styles.frame}>
        <div
          ref={track}
          className={`${styles.track} ${many ? '' : styles.single} ${locked ? styles.locked : ''}`}
          onScroll={handleScroll}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          onPointerCancel={handlePointerCancel}
          onKeyDown={handleKeyDown}
          tabIndex={many ? 0 : undefined}
          role={many ? 'region' : undefined}
          aria-roledescription={many ? '사진 슬라이드' : undefined}
          aria-label={many ? `${alt} ${photos.length}장` : undefined}
        >
          {photos.map((photo, i) =>
            renderSlide && canOpen?.(photo, i) === false ? (
              <div
                key={photo.id}
                className={`${styles.slide} ${styles.still}`}
                aria-hidden={many && i !== current ? true : undefined}
              >
                {renderSlide(photo, i)}
              </div>
            ) : (
              <button
                key={photo.id}
                type="button"
                className={styles.slide}
                onClick={(e) => handleClick(photo, e)}
                aria-label={`${alt} ${i + 1}번째 크게 보기`}
                aria-hidden={many && i !== current ? true : undefined}
                tabIndex={many && i !== current ? -1 : undefined}
                draggable={false}
              >
                {renderSlide ? (
                  renderSlide(photo, i)
                ) : (
                  // 가로 스크롤 칸 안에서는 사파리가 lazy 사진을 안 불러와서 eager
                  <ArtworkPhoto
                    key={photo.id}
                    artworkId={artworkId}
                    photoId={photo.id}
                    url={photo.url}
                    alt={`${alt} ${i + 1}`}
                    className={styles.image}
                    loading="eager"
                  />
                )}
              </button>
            ),
          )}
        </div>
        {many && (
          <>
            <span className={styles.counter} aria-live="polite">
              {current + 1} / {photos.length}
            </span>
            <button
              type="button"
              className={`${styles.arrow} ${styles.prev}`}
              onClick={() => go(current - 1)}
              disabled={current === 0}
              aria-label="이전 사진"
            >
              <ChevronLeft size={20} aria-hidden />
            </button>
            <button
              type="button"
              className={`${styles.arrow} ${styles.next}`}
              onClick={() => go(current + 1)}
              disabled={current === photos.length - 1}
              aria-label="다음 사진"
            >
              <ChevronRight size={20} aria-hidden />
            </button>
          </>
        )}
      </div>
      {many && (
        <div className={styles.dots} role="tablist" aria-label="사진 고르기">
          {photos.map((photo, i) => (
            <button
              key={photo.id}
              type="button"
              role="tab"
              aria-selected={i === current}
              aria-label={`${i + 1}번째 사진`}
              className={styles.dot}
              onClick={() => go(i)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

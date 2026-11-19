import { useEffect, useRef, useState } from 'react'
import introEnd from '../../../assets/mascot/mascot-intro-end.webp'
import introMov from '../../../assets/mascot/mascot-intro.mov'
import introWebm from '../../../assets/mascot/mascot-intro.webm'
import styles from './LandingTitle.module.css'

const WORDS = [
  { text: 'ART', tone: 'ink' },
  { text: 'MATE', tone: 'paint' },
]

/** 이 시간 안에 재생이 시작되지 않으면(느린 망, 저전력 모드 등) 마지막 장면 그림으로 바꿈 */
const START_TIMEOUT_MS = 3000

function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/**
 * 투명 영상은 브라우저마다 되는 형식이 달라서 직접 고름
 * - Apple 엔진(맥 사파리, 아이폰·아이패드의 모든 브라우저): 투명 WebM을 못 그림 → 투명 HEVC(.mov)
 * - 그 밖(크롬·엣지·파이어폭스): 투명 HEVC를 못 그림 → 투명 WebM
 * <source type="..."> 로 맡기면 사파리가 WebM을 골라 버리거나 크롬이 HEVC를 골라 배경이 검게 나옴
 */
function pickIntroSrc() {
  return navigator.vendor?.startsWith('Apple') ? introMov : introWebm
}

/**
 * 첫 화면 ART MATE
 * 투명 배경 영상(5초): 고양이가 붓을 타고 날아와 내려서 주황 줄을 칠하고, 다시 붓을 타고 둥실 떠오름.
 * 영상 속 줄이 칠해지는 동안(1.9–3.3초) 그 아래 글자가 왼쪽부터 나타나고, 영상은 마지막 장면에서 멈춤.
 * 영상 형식은 pickIntroSrc 참고 (사파리 = HEVC, 나머지 = WebM).
 * 움직임 줄이기 설정이거나 재생이 안 되면 마지막 장면 그림 + 글자를 바로 보여 줌.
 * 화면 낭독기는 "ART MATE"만 읽음
 */
export default function LandingTitle() {
  const videoRef = useRef(null)
  // loading: 재생 기다리는 중 / playing: 재생 중(글자 칠하기) / still: 마지막 장면 그림
  const [phase, setPhase] = useState(() => (prefersReducedMotion() ? 'still' : 'loading'))

  useEffect(() => {
    if (phase !== 'loading') return undefined
    let settled = false
    const settle = (next) => {
      if (settled) return
      settled = true
      setPhase(next)
    }
    const timer = setTimeout(() => settle('still'), START_TIMEOUT_MS)
    videoRef.current
      ?.play()
      .then(() => settle('playing'))
      .catch(() => settle('still'))
    return () => {
      settled = true
      clearTimeout(timer)
    }
  }, [phase])

  return (
    <span className={`${styles.box} ${styles[phase]}`}>
      <span className={styles.srOnly}>ART MATE</span>

      <span className={styles.stage} aria-hidden>
        {phase === 'still' ? (
          <img className={styles.media} src={introEnd} alt="" />
        ) : (
          <video
            ref={videoRef}
            className={styles.media}
            muted
            playsInline
            preload="auto"
            disablePictureInPicture
            src={pickIntroSrc()}
          />
        )}
      </span>

      <span className={styles.visual} aria-hidden>
        {WORDS.map((word) => (
          <span key={word.text} className={styles[word.tone]}>
            {word.text}
          </span>
        ))}
      </span>
    </span>
  )
}

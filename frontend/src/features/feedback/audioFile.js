// 녹음 파일 업로드용 검사 (서버 제한: backend/.env.example RECORDING_*)

export const MAX_AUDIO_BYTES = 25 * 1024 * 1024
export const MAX_AUDIO_MS = 20 * 60 * 1000

// 브라우저가 붙이는 별칭(audio/x-m4a 등)은 저장소 버킷이 거절하므로 표준 형식으로 바꿔서 보냄
const ALIASES = {
  'audio/x-wav': 'audio/wav',
  'audio/wave': 'audio/wav',
  'audio/x-m4a': 'audio/mp4',
  'audio/m4a': 'audio/mp4',
  'audio/mp3': 'audio/mpeg',
}
const BY_EXTENSION = {
  webm: 'audio/webm',
  ogg: 'audio/ogg',
  oga: 'audio/ogg',
  opus: 'audio/ogg',
  m4a: 'audio/mp4',
  mp4: 'audio/mp4',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
}
const ALLOWED = new Set(Object.values(BY_EXTENSION))

export const ACCEPT = '.m4a,.mp3,.wav,.webm,.ogg,.opus,.mp4,audio/*'

/** 서버가 받는 표준 MIME. 지원하지 않으면 null */
export function audioTypeOf(file) {
  const base = file.type.split(';')[0].trim().toLowerCase()
  const fromType = ALIASES[base] ?? base
  if (ALLOWED.has(fromType)) return fromType
  // 형식이 비어 있거나 video/mp4 등으로 잡히면 확장자로 판단
  const ext = file.name.split('.').pop()?.toLowerCase()
  return BY_EXTENSION[ext] ?? null
}

/** 오디오 길이(ms). WebM처럼 길이 정보가 없는 파일은 끝으로 이동시켜 알아냄 */
export function readDurationMs(url) {
  return new Promise((resolve, reject) => {
    const audio = new Audio()
    audio.preload = 'metadata'
    const done = (ms) => {
      audio.removeAttribute('src')
      audio.load()
      resolve(ms)
    }
    audio.addEventListener('error', () => reject(new Error('decode')))
    audio.addEventListener('loadedmetadata', () => {
      if (Number.isFinite(audio.duration)) return done(Math.round(audio.duration * 1000))
      audio.addEventListener(
        'durationchange',
        () => Number.isFinite(audio.duration) && done(Math.round(audio.duration * 1000)),
      )
      audio.currentTime = 1e7
    })
    audio.src = url
  })
}

// 녹음에 실제 소리가 들어 있는지 검사 (v0.9.4)
//
// 재생해도 아무 소리가 안 나는 녹음, 그리고 Whisper가 무음에서 엉뚱한 문장을 만들어 내는
// 문제(환각)를 업로드·변환 전에 잡기 위한 순수 함수와 실시간 입력 감시.

// 100ms 단위 RMS가 이 값을 넘으면 "소리가 있는 구간"으로 본다 (-40dBFS)
const SPEECH_RMS = 0.01
const FRAME_SEC = 0.1

/**
 * samples(Float32Array) → { peak, rmsDb, speechRatio }
 *  - peak: 가장 큰 진폭 (0~1)
 *  - rmsDb: 전체 평균 음량 (dBFS)
 *  - speechRatio: 소리가 있는 100ms 구간의 비율 (0~1)
 */
export function signalStats(samples, sampleRate) {
  const frame = Math.max(1, Math.round(sampleRate * FRAME_SEC))
  let peak = 0
  let total = 0
  let frames = 0
  let loud = 0
  for (let start = 0; start < samples.length; start += frame) {
    const end = Math.min(start + frame, samples.length)
    let sum = 0
    for (let i = start; i < end; i += 1) {
      const v = samples[i]
      sum += v * v
      const a = Math.abs(v)
      if (a > peak) peak = a
    }
    total += sum
    frames += 1
    if (Math.sqrt(sum / (end - start)) > SPEECH_RMS) loud += 1
  }
  const mean = samples.length ? total / samples.length : 0
  return {
    peak: Math.round(peak * 1000) / 1000,
    rmsDb: Math.round(10 * Math.log10(mean + 1e-12) * 10) / 10,
    speechRatio: frames ? Math.round((loud / frames) * 100) / 100 : 0,
  }
}

/**
 * 'silent' 거의 무음 (재생해도 들리지 않음, 변환하면 환각 위험)
 * 'quiet'  소리가 아주 작거나 짧음 (변환 정확도가 크게 떨어질 수 있음)
 * 'ok'
 */
export function judgeSignal(stats) {
  if (!stats) return 'ok'
  if (stats.peak < 0.01 || stats.speechRatio < 0.02) return 'silent'
  if (stats.peak < 0.05 || stats.speechRatio < 0.1) return 'quiet'
  return 'ok'
}

/**
 * 녹음 중 마이크 입력 감시 (Web Audio AnalyserNode). 소리를 바꾸지 않고 읽기만 한다.
 * onSilent(true|false): 입력이 silentMs 동안 계속 거의 없으면 true
 * → { stop(): 누적 통계 { peak, speechRatio } }
 */
export function watchInputLevel(stream, { onSilent, silentMs = 4000 } = {}) {
  const Ctx = globalThis.AudioContext ?? globalThis.webkitAudioContext
  if (!Ctx) return { stop: () => null }
  let ctx
  try {
    ctx = new Ctx()
  } catch {
    return { stop: () => null }
  }
  const source = ctx.createMediaStreamSource(stream)
  const analyser = ctx.createAnalyser()
  analyser.fftSize = 2048
  source.connect(analyser) // 스피커(destination)에는 연결하지 않음
  // iOS Safari: 사용자 동작 밖에서 만든 AudioContext는 정지 상태 → 값이 0으로 읽혀 오경보가 남.
  // 실행 중일 때만 재고, 끝까지 실행되지 않으면 "모름"(null)
  ctx.resume?.().catch(() => {})
  const buffer = new Float32Array(analyser.fftSize)
  let peak = 0
  let frames = 0
  let loud = 0
  let quietSince = performance.now()
  let silent = false
  const timer = setInterval(() => {
    if (ctx.state !== 'running') {
      quietSince = performance.now()
      return
    }
    analyser.getFloatTimeDomainData(buffer)
    let sum = 0
    for (const v of buffer) {
      sum += v * v
      const a = Math.abs(v)
      if (a > peak) peak = a
    }
    frames += 1
    const now = performance.now()
    if (Math.sqrt(sum / buffer.length) > SPEECH_RMS) {
      loud += 1
      quietSince = now
      if (silent) {
        silent = false
        onSilent?.(false)
      }
    } else if (!silent && now - quietSince > silentMs) {
      silent = true
      onSilent?.(true)
    }
  }, 100)
  return {
    stop() {
      clearInterval(timer)
      source.disconnect()
      ctx.close?.()
      return frames
        ? { peak: Math.round(peak * 1000) / 1000, speechRatio: Math.round((loud / frames) * 100) / 100 }
        : null
    },
  }
}

/** 파일(Blob)을 디코딩해 통계. 길면(메모리) 검사하지 않음 → null */
export async function analyzeBlob(blob, { maxMs = 5 * 60 * 1000, durationMs } = {}) {
  if (durationMs && durationMs > maxMs) return null
  const Ctx = globalThis.AudioContext ?? globalThis.webkitAudioContext
  if (!Ctx) return null
  const ctx = new Ctx()
  try {
    const buffer = await ctx.decodeAudioData(await blob.arrayBuffer())
    return signalStats(buffer.getChannelData(0), buffer.sampleRate)
  } catch {
    return null
  } finally {
    ctx.close?.()
  }
}

// 브라우저 STT 클라이언트: 기능 감지 · 음성 디코딩(16kHz mono) · Worker 호출
import { PREFERENCE_KEY, chooseModel, looksDegenerate, toSegments } from './models'

const SAMPLE_RATE = 16_000

let capsPromise = null
let worker = null
let nextId = 1
const pending = new Map()
let progressListener = null

/** 기능 감지 (한 번만). WebGPU가 없으면 WASM으로 대체 */
export function detectCapabilities() {
  capsPromise ??= (async () => {
    const caps = {
      worker: typeof Worker !== 'undefined',
      wasm: typeof WebAssembly === 'object',
      audio: typeof OfflineAudioContext !== 'undefined',
      webgpu: false,
      shaderF16: false,
      deviceMemory: navigator.deviceMemory ?? null,
    }
    if (navigator.gpu) {
      try {
        const adapter = await navigator.gpu.requestAdapter()
        caps.webgpu = Boolean(adapter)
        caps.shaderF16 = Boolean(adapter?.features?.has('shader-f16'))
      } catch {
        caps.webgpu = false
      }
    }
    return caps
  })()
  return capsPromise
}

export function getPreference() {
  try {
    return localStorage.getItem(PREFERENCE_KEY) ?? 'auto'
  } catch {
    return 'auto'
  }
}

export function setPreference(value) {
  try {
    localStorage.setItem(PREFERENCE_KEY, value)
  } catch {
    // 저장소를 쓸 수 없으면 이번 화면에서만 적용
  }
}

/** 사용할 모델 (null이면 브라우저 STT 안 함 → 서버 처리) */
export async function resolvePlan(preference = getPreference()) {
  const caps = await detectCapabilities()
  if (!caps.audio) return null
  return chooseModel(caps, preference)
}

/** 녹음 Blob → 16kHz mono Float32Array (AudioContext는 Worker에서 쓸 수 없어 화면 스레드에서) */
export async function decodeAudio(blob) {
  const Ctx = window.AudioContext ?? window.webkitAudioContext
  const ctx = new Ctx()
  try {
    const buffer = await ctx.decodeAudioData(await blob.arrayBuffer())
    const offline = new OfflineAudioContext(1, Math.ceil(buffer.duration * SAMPLE_RATE), SAMPLE_RATE)
    const source = offline.createBufferSource()
    source.buffer = buffer
    source.connect(offline.destination)
    source.start()
    const rendered = await offline.startRendering()
    return { audio: rendered.getChannelData(0), durationMs: Math.round(buffer.duration * 1000) }
  } finally {
    ctx.close?.()
  }
}

function getWorker() {
  if (worker) return worker
  worker = new Worker(new URL('./sttWorker.js', import.meta.url), { type: 'module' })
  worker.onmessage = ({ data }) => {
    if (data.type === 'progress') {
      progressListener?.(data)
      return
    }
    const entry = pending.get(data.id)
    if (!entry) return
    pending.delete(data.id)
    if (data.type === 'error') entry.reject(new Error(data.message))
    else entry.resolve(data)
  }
  worker.onerror = (event) => {
    for (const entry of pending.values()) entry.reject(new Error(event.message || 'worker error'))
    pending.clear()
    worker?.terminate()
    worker = null
  }
  return worker
}

function call(message, transfer = []) {
  const id = nextId++
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    getWorker().postMessage({ ...message, id }, transfer)
  })
}

/** 진행 중인 브라우저 STT 중단 (모델·Worker를 버림 → 다음에 다시 로드) */
export function cancelBrowserStt() {
  for (const entry of pending.values()) entry.reject(new Error('cancelled'))
  pending.clear()
  worker?.terminate()
  worker = null
}

/**
 * Blob 전사. onStage('loading'|'transcribing'), onProgress({ loaded, total, progress })
 * → { segments, model, device, size, timings: { decodeMs, loadMs, modelReused, transcribeMs, totalMs } }
 *   modelReused: 이미 메모리에 올라온 모델을 그대로 씀 (loadMs 0)
 */
export async function transcribeBlob(blob, plan, { onStage, onProgress } = {}) {
  const started = performance.now()
  const decodeStarted = performance.now()
  const { audio, durationMs } = await decodeAudio(blob)
  const decodeMs = Math.round(performance.now() - decodeStarted)

  onStage?.('loading')
  progressListener = onProgress
  let loaded
  try {
    loaded = await call({ type: 'load', model: plan.model, device: plan.device, dtype: plan.dtype })
  } finally {
    progressListener = null
  }

  onStage?.('transcribing')
  const { output, transcribeMs } = await call({ type: 'transcribe', audio }, [audio.buffer])
  const segments = toSegments(output, durationMs)
  if (!segments.length) throw new Error('empty transcript')
  if (looksDegenerate(segments)) throw new Error('repetitive transcript')
  return {
    segments,
    model: plan.model,
    device: plan.device,
    size: plan.size,
    durationMs,
    timings: {
      decodeMs,
      loadMs: loaded.loadMs,
      modelReused: loaded.reused,
      transcribeMs,
      totalMs: Math.round(performance.now() - started),
    },
  }
}

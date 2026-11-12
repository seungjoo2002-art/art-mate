// 브라우저 STT 클라이언트: 기능 감지 · 음성 디코딩(16kHz mono) · Worker 호출 · 구간별 변환
import { SAMPLE_RATE, mergeChunkSegments, planChunks } from './chunks'
import { PREFERENCE_KEY, chooseModel, isMobileDevice, looksDegenerate, toSegments } from './models'

// 이 기기에서 변환 중 탭이 강제 종료된 기록 → 'wasm' (WebGPU 사용 안 함). deviceJobs.js가 기록
export const SAFETY_KEY = 'artmate.stt.safety'
// WASM 정밀도 (WebGPU 초기화 실패 시 Worker 안에서 바로 이 설정으로 다시 시도)
const WASM_DTYPE = { encoder_model: 'q8', decoder_model_merged: 'q8' }
// 모델 준비 정지 감시: 다운로드가 진행되는 동안은 계속 기다리고, 이 시간 동안 아무 진행이 없으면
// 중단 (파일을 다 받은 뒤 추론 세션 준비 — WASM 컴파일·GPU 셰이더 — 도 이 안에 끝나야 함)
const LOAD_STALL_MS = 180_000
// 30초 이하 구간 하나 변환 제한 (느린 휴대폰 WASM 기준 여유)
const CHUNK_TIMEOUT_MS = 180_000
// 마지막 사용 후 이 시간이 지나면 Worker를 닫아 메모리를 돌려줌 (모델 파일은 캐시에 남음)
const IDLE_RELEASE_MS = 5 * 60_000

let capsPromise = null
let worker = null
let nextId = 1
const pending = new Map()
let progressListener = null
let idleTimer = null

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
      mobile: isMobileDevice(),
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

function readStorage(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function writeStorage(key, value) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // 저장소를 쓸 수 없으면 이번 화면에서만 적용
  }
}

export const getPreference = () => readStorage(PREFERENCE_KEY, 'auto')
export const setPreference = (value) => writeStorage(PREFERENCE_KEY, value)
export const getSafety = () => readStorage(SAFETY_KEY, 'normal')
export const setSafety = (value) => writeStorage(SAFETY_KEY, value === 'normal' ? null : value)

/** 사용할 모델 (null이면 브라우저 STT 안 함 → 서버 처리) */
export async function resolvePlan(preference = getPreference()) {
  const caps = await detectCapabilities()
  if (!caps.audio) return null
  return chooseModel(caps, preference, getSafety())
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

function dropWorker(reason) {
  for (const entry of pending.values()) entry.reject(new Error(reason))
  pending.clear()
  worker?.terminate()
  worker = null
}

function getWorker() {
  if (worker) return worker
  worker = new Worker(new URL('./sttWorker.js', import.meta.url), { type: 'module' })
  worker.onmessage = ({ data }) => {
    if (data.type === 'progress' || data.type === 'fallback') {
      progressListener?.(data)
      return
    }
    const entry = pending.get(data.id)
    if (!entry) return
    pending.delete(data.id)
    if (data.type === 'error') entry.reject(new Error(data.message))
    else entry.resolve(data)
  }
  // Worker 스크립트를 못 받음(배포 교체 직후 옛 파일 404 등)·Worker 안의 처리되지 않은 오류.
  // 앱 화면에는 영향 없이 이 변환만 실패 → 서버 처리로 넘어간다
  worker.onerror = (event) => {
    event.preventDefault?.()
    dropWorker(event.message || 'worker error')
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

/** 제한 시간 안에 끝나지 않으면 Worker를 닫고(모델 해제) 'stalled'로 실패 */
function withDeadline(promise, ms, setRestart) {
  return new Promise((resolve, reject) => {
    let timer = null
    const arm = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        dropWorker('stalled')
        reject(new Error('stalled'))
      }, ms)
    }
    setRestart?.(arm)
    arm()
    promise.then(
      (value) => {
        clearTimeout(timer)
        resolve(value)
      },
      (error) => {
        clearTimeout(timer)
        reject(error)
      },
    )
  })
}

function keepAlive() {
  clearTimeout(idleTimer)
  idleTimer = null
}

/** 다음 변환이 없으면 잠시 뒤 Worker를 닫아 메모리를 돌려준다 (휴대폰 탭 강제 종료 예방) */
export function releaseModelLater() {
  clearTimeout(idleTimer)
  idleTimer = setTimeout(() => {
    if (pending.size === 0) dropWorker('released')
  }, IDLE_RELEASE_MS)
}

/** 진행 중인 브라우저 STT 중단 (모델·Worker를 버림 → 다음에 다시 로드) */
export function cancelBrowserStt() {
  dropWorker('cancelled')
}

/**
 * 모델 준비 (다운로드·캐시 읽기 + 추론 세션). 이미 올라와 있으면 바로 끝남.
 * onProgress({ loaded, total, progress }): 실제 받은 바이트 / onFallback({ from }): WebGPU 실패 → WASM
 */
export async function loadModel(plan, { onProgress, onFallback } = {}) {
  keepAlive()
  let restart = null
  progressListener = (data) => {
    if (data.type === 'fallback') {
      restart?.()
      onFallback?.(data)
      return
    }
    restart?.() // 진행 중이면 정지 감시 시간을 다시 잼
    onProgress?.(data)
  }
  try {
    const loaded = await withDeadline(
      call({
        type: 'load',
        model: plan.model,
        device: plan.device,
        dtype: plan.dtype,
        fallbackDtype: plan.device === 'webgpu' ? WASM_DTYPE : null,
      }),
      LOAD_STALL_MS,
      (arm) => {
        restart = arm
      },
    )
    return loaded
  } finally {
    progressListener = null
  }
}

/** 녹음 직후 모델만 미리 준비 (저장 버튼을 누르기 전에 시간이 오래 걸리는 단계를 끝내 둠) */
export async function prewarm(plan, handlers) {
  try {
    const loaded = await loadModel(plan, handlers)
    releaseModelLater()
    return loaded
  } catch {
    return null // 실제 변환 때 다시 시도
  }
}

/**
 * Blob 전사 (구간별).
 * onStage('decoding'|'loading'|'transcribing'), onProgress(다운로드), onFallback,
 * onChunk({ index, total, segments, offsetMs, bounds }): 구간 하나 끝날 때마다 (중간 결과 저장용)
 * resume: { bounds, parts } 이전에 끝난 구간들 (같은 녹음·같은 구간일 때만 이어서)
 * → { segments, model, device, size, durationMs, chunkCount, timings }
 */
export async function transcribeBlob(blob, plan, { onStage, onProgress, onFallback, onChunk, resume } = {}) {
  keepAlive()
  const started = performance.now()
  onStage?.('decoding')
  const decodeStarted = performance.now()
  const { audio, durationMs } = await decodeAudio(blob)
  const decodeMs = Math.round(performance.now() - decodeStarted)
  const bounds = planChunks(audio)
  const sameBounds =
    resume?.bounds?.length === bounds.length &&
    resume.bounds.every((b, i) => b.start === bounds[i].start && b.end === bounds[i].end)
  const parts = sameBounds ? [...resume.parts] : []

  onStage?.('loading', { chunkCount: bounds.length, done: parts.length })
  // 모든 구간이 이미 끝났으면(저장만 실패했던 경우) 모델을 다시 올리지 않는다
  const loaded =
    parts.length === bounds.length
      ? { reused: true, device: plan.device, loadMs: 0, fileMs: 0, initMs: 0, fromCache: true }
      : await loadModel(plan, { onProgress, onFallback })

  onStage?.('transcribing', { chunkCount: bounds.length, done: parts.length })
  let transcribeMs = 0
  for (let index = parts.length; index < bounds.length; index += 1) {
    const { start, end } = bounds[index]
    const slice = audio.slice(start, end) // 복사본을 Worker로 넘김 (원본은 다음 구간에 필요)
    const chunkMs = Math.round(((end - start) / SAMPLE_RATE) * 1000)
    const result = await withDeadline(call({ type: 'transcribe', audio: slice }, [slice.buffer]), CHUNK_TIMEOUT_MS)
    transcribeMs += result.transcribeMs
    const part = {
      offsetMs: Math.round((start / SAMPLE_RATE) * 1000),
      segments: toSegments(result.output, chunkMs),
    }
    parts.push(part)
    onChunk?.({ index, total: bounds.length, bounds, parts })
  }

  const segments = mergeChunkSegments(parts, durationMs)
  if (!segments.length) throw new Error('empty transcript')
  if (looksDegenerate(segments)) throw new Error('repetitive transcript')
  return {
    segments,
    model: plan.model,
    // WebGPU 초기화가 실패해 WASM으로 바뀌었으면 실제 사용한 장치를 저장
    device: loaded.device ?? plan.device,
    size: plan.size,
    durationMs,
    chunkCount: bounds.length,
    timings: {
      decodeMs,
      loadMs: loaded.loadMs,
      fileMs: loaded.fileMs,
      initMs: loaded.initMs,
      fromCache: loaded.fromCache,
      modelReused: loaded.reused,
      fallbackFrom: loaded.fallbackFrom ?? null,
      transcribeMs,
      resumedChunks: sameBounds ? resume.parts.length : 0,
      totalMs: Math.round(performance.now() - started),
    },
  }
}

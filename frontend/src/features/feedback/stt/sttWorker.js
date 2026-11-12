// Web Worker: Transformers.js Whisper 실행 (UI 스레드를 막지 않음)
// 음성 데이터는 이 기기 안에서만 처리한다. 네트워크는 모델 파일(huggingface.co)과
// ONNX Runtime WASM(cdn.jsdelivr.net) 다운로드에만 쓰이며 브라우저 Cache Storage에 저장된다.
//
// 메시지
//  load       { model, device, dtype, fallbackDtype } → loaded { reused, device, fromCache, fileMs, initMs, loadMs, fallbackFrom? }
//             (같은 모델이 이미 올라와 있으면 재사용, 동시에 두 번 요청돼도 한 번만 로드)
//  transcribe { audio(Float32Array, 30초 이하) } → result { output, transcribeMs }
//  dispose    모델 해제 (메모리 반환)
import { env, pipeline } from '@huggingface/transformers'

env.allowLocalModels = false
env.useBrowserCache = true

const CACHE_NAME = 'transformers-cache'

let transcriber = null
let loadedKey = null
let loadedDevice = null
let loading = null // { key, promise }

function post(type, payload) {
  self.postMessage({ type, ...payload })
}

async function isCached(model) {
  try {
    const cache = await caches.open(CACHE_NAME)
    const keys = await cache.keys()
    return keys.some((request) => request.url.includes(`/${model}/`))
  } catch {
    return false
  }
}

async function createPipeline(model, device, dtype, timing) {
  return pipeline('automatic-speech-recognition', model, {
    device,
    dtype,
    progress_callback: (p) => {
      if (p.status === 'initiate') timing.fileStart ??= performance.now()
      if (p.status === 'done') timing.fileEnd = performance.now()
      if (p.status === 'progress_total') {
        // 실제 받은 바이트 기준 (캐시에서 읽을 때도 발생)
        post('progress', { loaded: p.loaded, total: p.total, progress: p.progress })
      }
    },
  })
}

async function load({ model, device, dtype, fallbackDtype }) {
  const key = `${model}|${device}|${JSON.stringify(dtype)}`
  if (transcriber && loadedKey === key) {
    return { reused: true, device: loadedDevice, loadMs: 0, fileMs: 0, initMs: 0, fromCache: true }
  }
  if (loading?.key === key) return loading.promise
  const promise = (async () => {
    if (transcriber) {
      await transcriber.dispose?.()
      transcriber = null
      loadedKey = null
    }
    const fromCache = await isCached(model)
    const started = performance.now()
    const timing = {}
    let usedDevice = device
    let fallbackFrom = null
    try {
      transcriber = await createPipeline(model, device, dtype, timing)
    } catch (error) {
      if (device !== 'webgpu' || !fallbackDtype) throw error
      // WebGPU 초기화 실패(어댑터 없음·GPU 메모리 부족 등) → 같은 모델을 WASM으로 다시 시도
      fallbackFrom = 'webgpu'
      usedDevice = 'wasm'
      post('fallback', { from: 'webgpu', message: String(error?.message ?? error).slice(0, 200) })
      transcriber = await createPipeline(model, 'wasm', fallbackDtype, timing)
    }
    loadedKey = key
    loadedDevice = usedDevice
    const loadMs = Math.round(performance.now() - started)
    const fileMs = timing.fileStart && timing.fileEnd ? Math.round(timing.fileEnd - timing.fileStart) : null
    return {
      reused: false,
      device: usedDevice,
      fallbackFrom,
      fromCache,
      loadMs,
      fileMs, // 모델 파일 받기(또는 캐시에서 읽기)
      initMs: fileMs === null ? null : Math.max(0, loadMs - fileMs), // 추론 세션 준비
    }
  })()
  loading = { key, promise }
  try {
    return await promise
  } finally {
    loading = null
  }
}

self.onmessage = async ({ data }) => {
  const { id, type } = data
  try {
    if (type === 'load') {
      const info = await load(data)
      post('loaded', { id, ...info })
    } else if (type === 'transcribe') {
      if (!transcriber) throw new Error('model not loaded')
      const started = performance.now()
      // 30초 이하 구간만 받으므로 내부 분할(chunk_length_s) 없이 한 번에 처리
      const output = await transcriber(data.audio, {
        language: 'korean',
        task: 'transcribe',
        return_timestamps: true,
      })
      post('result', { id, output, transcribeMs: Math.round(performance.now() - started) })
    } else if (type === 'dispose') {
      await transcriber?.dispose?.()
      transcriber = null
      loadedKey = null
      loadedDevice = null
      post('disposed', { id })
    }
  } catch (error) {
    // 오류 메시지에 음성·전사 내용은 들어가지 않는다
    post('error', { id, message: String(error?.message ?? error).slice(0, 300) })
  }
}

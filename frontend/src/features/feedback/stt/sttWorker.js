// Web Worker: Transformers.js Whisper 실행 (UI 스레드를 막지 않음)
// 음성 데이터는 이 기기 안에서만 처리한다. 네트워크는 모델 파일(huggingface.co)과
// ONNX Runtime WASM(cdn.jsdelivr.net) 다운로드에만 쓰이며 브라우저 Cache Storage에 저장된다.
import { env, pipeline } from '@huggingface/transformers'

env.allowLocalModels = false
env.useBrowserCache = true

let transcriber = null
let loadedKey = null

function post(type, payload) {
  self.postMessage({ type, ...payload })
}

async function load({ model, device, dtype }) {
  const key = `${model}|${device}|${JSON.stringify(dtype)}`
  if (transcriber && loadedKey === key) return { reused: true, loadMs: 0 }
  if (transcriber) {
    await transcriber.dispose?.()
    transcriber = null
  }
  const started = performance.now()
  transcriber = await pipeline('automatic-speech-recognition', model, {
    device,
    dtype,
    progress_callback: (p) => {
      if (p.status === 'progress_total') {
        post('progress', { loaded: p.loaded, total: p.total, progress: p.progress })
      }
    },
  })
  loadedKey = key
  return { reused: false, loadMs: Math.round(performance.now() - started) }
}

self.onmessage = async ({ data }) => {
  const { id, type } = data
  try {
    if (type === 'load') {
      const info = await load(data)
      post('loaded', { id, ...info })
    } else if (type === 'transcribe') {
      const started = performance.now()
      const output = await transcriber(data.audio, {
        language: 'korean',
        task: 'transcribe',
        return_timestamps: true,
        chunk_length_s: 30,
        stride_length_s: 5,
      })
      post('result', { id, output, transcribeMs: Math.round(performance.now() - started) })
    }
  } catch (error) {
    // 오류 메시지에 음성·전사 내용은 들어가지 않는다
    post('error', { id, message: String(error?.message ?? error).slice(0, 300) })
  }
}

// 브라우저 STT 모델 선택·결과 변환 (순수 함수, 테스트 대상)
// Whisper 다국어 ONNX 모델 (Hugging Face onnx-community). 한국어 고정.

export const MODELS = {
  tiny: { id: 'onnx-community/whisper-tiny', label: '빠르게 (tiny)' },
  base: { id: 'onnx-community/whisper-base', label: '기본 (base)' },
  small: { id: 'onnx-community/whisper-small', label: '정확하게 (small)' },
}

// 장치별 정밀도. WASM은 int8(작고 CPU에서 빠름), WebGPU는 인코더 fp32·fp16 + 디코더 q4
const DTYPE = {
  wasm: { encoder_model: 'q8', decoder_model_merged: 'q8' },
  webgpu: { encoder_model: 'fp32', decoder_model_merged: 'q4' },
  webgpuF16: { encoder_model: 'fp16', decoder_model_merged: 'q4' },
}

// 첫 다운로드 크기 안내용 (MB, Hugging Face 파일 크기 기준 근삿값)
const DOWNLOAD_MB = {
  wasm: { tiny: 41, base: 77, small: 249 },
  webgpu: { tiny: 120, base: 206, small: 586 },
  webgpuF16: { tiny: 103, base: 165, small: 410 },
}

export const PREFERENCES = ['auto', 'tiny', 'base', 'small', 'off']
export const PREFERENCE_KEY = 'artmate.stt.model'

/**
 * caps: { worker, wasm, webgpu, shaderF16, deviceMemory }
 * preference: 'auto' | 'tiny' | 'base' | 'small' | 'off'
 * → null(브라우저 STT 안 함 → 서버 처리) 또는 { size, model, device, dtype, downloadMb }
 */
export function chooseModel(caps, preference = 'auto') {
  if (preference === 'off' || !caps.worker || !caps.wasm) return null
  const device = caps.webgpu ? 'webgpu' : 'wasm'
  const precision = caps.webgpu ? (caps.shaderF16 ? 'webgpuF16' : 'webgpu') : 'wasm'
  let size = preference
  if (preference === 'auto') {
    // 기본 base. 메모리가 아주 적은 기기는 tiny (deviceMemory는 Chrome 계열만 제공)
    size = caps.deviceMemory && caps.deviceMemory <= 2 ? 'tiny' : 'base'
  }
  if (!MODELS[size]) return null
  return {
    size,
    model: MODELS[size].id,
    device,
    dtype: DTYPE[precision],
    downloadMb: DOWNLOAD_MB[precision][size],
  }
}

const MAX_TEXT = 1000

/**
 * Transformers.js 결과 { text, chunks: [{ timestamp: [start, end|null], text }] } →
 * 백엔드 BrowserSegment [{ start_ms, end_ms, text }] (빈 문장 제거, 순서·범위 보정)
 */
export function toSegments(output, durationMs) {
  const chunks = output?.chunks?.length
    ? output.chunks
    : [{ timestamp: [0, durationMs / 1000], text: output?.text ?? '' }]
  const segments = []
  let lastStart = 0
  for (const chunk of chunks) {
    const text = (chunk.text ?? '').trim()
    if (!text) continue
    const [rawStart, rawEnd] = chunk.timestamp ?? [0, null]
    let start = Math.round((rawStart ?? 0) * 1000)
    let end = rawEnd == null ? durationMs : Math.round(rawEnd * 1000)
    start = Math.min(Math.max(start, lastStart), durationMs)
    end = Math.min(Math.max(end, start), durationMs)
    lastStart = start
    for (let i = 0; i < text.length; i += MAX_TEXT) {
      segments.push({ start_ms: start, end_ms: end, text: text.slice(i, i + MAX_TEXT).trim() })
    }
  }
  return segments.filter((s) => s.text)
}

/** 반복 환각(같은 구간이 계속 반복) 의심: 서로 같은 문장이 절반 이상이면 실패로 보고 서버 처리 */
export function looksDegenerate(segments) {
  if (segments.length < 4) return false
  const unique = new Set(segments.map((s) => s.text))
  return unique.size <= segments.length / 2
}

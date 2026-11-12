// 긴 녹음(최대 5분 권장)을 구간별로 나눠 변환하기 위한 순수 함수 (테스트 대상)
//
// 왜 직접 나누나:
//  - 실제 진행률(완료 구간 수 / 전체 구간 수)을 보여 줄 수 있다 (임의의 % 표시 없음)
//  - 구간마다 결과를 기기에 저장해 두면 탭이 강제로 닫혀도 이어서 변환할 수 있다
//  - Whisper 입력 창(30초)보다 짧게 잘라 한 번에 쓰는 메모리를 일정하게 유지한다
//
// 겹침(stride) 없이 "가장 조용한 지점"에서 자르므로 같은 문장이 두 구간에 들어가 중복되지 않는다.
// 말이 끊기지 않고 30초 넘게 이어지면 그 범위에서 가장 조용한 곳(숨 쉬는 틈)에서 자른다.

export const SAMPLE_RATE = 16_000
const FRAME_MS = 100
const WINDOW_SEC = 30 // Whisper 한 번 입력 길이

/**
 * samples(Float32Array, 16kHz mono) → [{ start, end }] (샘플 인덱스, end 미포함)
 * 구간 길이 minSec~maxSec 사이에서 소리 에너지가 가장 낮은 100ms 지점에서 자른다.
 */
export function planChunks(samples, { sampleRate = SAMPLE_RATE, minSec = 18, maxSec = 28 } = {}) {
  const total = samples.length
  const maxLen = Math.round(maxSec * sampleRate)
  const minLen = Math.round(minSec * sampleRate)
  const frame = Math.round((FRAME_MS / 1000) * sampleRate)
  if (total <= maxLen) return total ? [{ start: 0, end: total }] : []

  const chunks = []
  let start = 0
  while (total - start > maxLen) {
    let bestCut = start + maxLen
    let bestEnergy = Infinity
    // 뒤쪽(긴 구간)부터 보며 더 조용한 곳을 찾는다 → 같은 조용함이면 긴 구간을 택함
    for (let cut = start + maxLen - frame; cut >= start + minLen; cut -= frame) {
      const energy = frameEnergy(samples, cut, frame)
      if (energy < bestEnergy) {
        bestEnergy = energy
        bestCut = cut + Math.floor(frame / 2)
      }
    }
    chunks.push({ start, end: bestCut })
    start = bestCut
  }
  // 아주 짧은 꼬리(2초 미만)는 앞 구간에 붙인다. 단 Whisper 입력 창(30초)을 넘지 않을 때만
  const last = chunks[chunks.length - 1]
  if (total - start < 2 * sampleRate && total - last.start <= WINDOW_SEC * sampleRate) {
    last.end = total
    return chunks
  }
  chunks.push({ start, end: total })
  return chunks
}

function frameEnergy(samples, at, frame) {
  let sum = 0
  const end = Math.min(at + frame, samples.length)
  for (let i = at; i < end; i += 1) sum += samples[i] * samples[i]
  return sum / Math.max(1, end - at)
}

/**
 * 구간별 결과 → 전체 구간 목록. 각 구간의 segment 시각(구간 안 상대 ms)에 시작 시각을 더하고,
 * 순서·범위를 보정한다. 구간 경계에서 바로 앞 문장과 똑같은 문장은 한 번만 남긴다 (환각 반복 방지).
 * parts: [{ offsetMs, segments: [{ start_ms, end_ms, text }] }]
 */
export function mergeChunkSegments(parts, durationMs) {
  const merged = []
  let lastStart = 0
  for (const part of parts) {
    for (const seg of part.segments) {
      const text = seg.text.trim()
      if (!text) continue
      const start = Math.min(Math.max(part.offsetMs + seg.start_ms, lastStart), durationMs)
      const end = Math.min(Math.max(part.offsetMs + seg.end_ms, start), durationMs)
      const prev = merged[merged.length - 1]
      if (prev && prev.text === text && start - prev.end_ms < 2000) {
        prev.end_ms = Math.max(prev.end_ms, end)
        continue
      }
      merged.push({ start_ms: start, end_ms: end, text })
      lastStart = start
    }
  }
  return merged
}

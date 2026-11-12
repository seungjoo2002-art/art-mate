import { describe, expect, it } from 'vitest'
import { SAMPLE_RATE, mergeChunkSegments, planChunks } from './chunks'

/** 말소리(진폭 0.5) 사이사이에 무음(0)이 들어간 가짜 음성. pattern: [[초, 'speech'|'silence'], ...] */
function synth(pattern) {
  const total = pattern.reduce((sum, [sec]) => sum + sec, 0)
  const samples = new Float32Array(Math.round(total * SAMPLE_RATE))
  let at = 0
  for (const [sec, kind] of pattern) {
    const n = Math.round(sec * SAMPLE_RATE)
    if (kind === 'speech') {
      for (let i = 0; i < n; i += 1) samples[at + i] = 0.5 * Math.sin(i / 7)
    }
    at += n
  }
  return samples
}

const seconds = (n) => n / SAMPLE_RATE

describe('planChunks', () => {
  it('keeps short recordings as one chunk', () => {
    const audio = synth([[20, 'speech']])
    expect(planChunks(audio)).toEqual([{ start: 0, end: audio.length }])
    expect(planChunks(new Float32Array(0))).toEqual([])
  })

  it('splits 5 minutes into contiguous chunks no longer than the Whisper window', () => {
    // 6초 말 + 0.4초 쉼 반복 → 약 5분
    const pattern = []
    while (pattern.reduce((s, [sec]) => s + sec, 0) < 300) pattern.push([6, 'speech'], [0.4, 'silence'])
    const audio = synth(pattern)
    const chunks = planChunks(audio)
    expect(chunks.length).toBeGreaterThanOrEqual(11)
    expect(chunks[0].start).toBe(0)
    expect(chunks.at(-1).end).toBe(audio.length)
    for (let i = 0; i < chunks.length; i += 1) {
      expect(seconds(chunks[i].end - chunks[i].start)).toBeLessThanOrEqual(30)
      if (i > 0) expect(chunks[i].start).toBe(chunks[i - 1].end) // 겹침·빈틈 없음
    }
    // 자른 곳은 모두 무음 안 (문장 중간을 자르지 않음)
    for (const { end } of chunks.slice(0, -1)) {
      expect(Math.abs(audio[end])).toBe(0)
    }
  })

  it('cuts at the quietest point even without full silence', () => {
    const audio = synth([[24, 'speech'], [0.3, 'silence'], [20, 'speech']])
    const [first] = planChunks(audio)
    expect(seconds(first.end)).toBeGreaterThan(24)
    expect(seconds(first.end)).toBeLessThan(24.3)
  })

  it('merges a tiny tail into the previous chunk when it still fits', () => {
    const audio = synth([[27.5, 'speech'], [0.2, 'silence'], [1, 'speech']])
    const chunks = planChunks(audio)
    expect(chunks).toHaveLength(1)
    expect(chunks[0].end).toBe(audio.length)
  })
})

describe('mergeChunkSegments', () => {
  it('offsets chunk-relative times and keeps order', () => {
    const merged = mergeChunkSegments(
      [
        { offsetMs: 0, segments: [{ start_ms: 0, end_ms: 3000, text: '구도가 좋아요.' }] },
        { offsetMs: 25_000, segments: [{ start_ms: 500, end_ms: 4000, text: '명암을 더 주세요.' }] },
      ],
      40_000,
    )
    expect(merged).toEqual([
      { start_ms: 0, end_ms: 3000, text: '구도가 좋아요.' },
      { start_ms: 25_500, end_ms: 29_000, text: '명암을 더 주세요.' },
    ])
  })

  it('drops an identical sentence repeated across a chunk boundary and blank text', () => {
    const merged = mergeChunkSegments(
      [
        { offsetMs: 0, segments: [{ start_ms: 20_000, end_ms: 25_000, text: '소실점을 맞춰요.' }] },
        {
          offsetMs: 25_000,
          segments: [
            { start_ms: 0, end_ms: 1000, text: '소실점을 맞춰요.' },
            { start_ms: 1000, end_ms: 2000, text: '  ' },
            { start_ms: 2000, end_ms: 5000, text: '채도를 낮춰요.' },
          ],
        },
      ],
      60_000,
    )
    expect(merged.map((s) => s.text)).toEqual(['소실점을 맞춰요.', '채도를 낮춰요.'])
    expect(merged[0].end_ms).toBe(26_000)
  })

  it('clamps to the recording length', () => {
    const merged = mergeChunkSegments(
      [{ offsetMs: 28_000, segments: [{ start_ms: 0, end_ms: 9000, text: '마무리' }] }],
      30_000,
    )
    expect(merged[0]).toEqual({ start_ms: 28_000, end_ms: 30_000, text: '마무리' })
  })
})

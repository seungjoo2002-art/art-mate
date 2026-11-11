import { describe, expect, it } from 'vitest'
import { MODELS, chooseModel, looksDegenerate, toSegments } from './models'
import { withTimeout } from './useBrowserStt'

const DESKTOP_GPU = { worker: true, wasm: true, webgpu: true, shaderF16: false, deviceMemory: 8 }
const NO_GPU = { worker: true, wasm: true, webgpu: false, shaderF16: false, deviceMemory: 4 }

describe('chooseModel', () => {
  it('defaults to whisper-base on WebGPU and WASM', () => {
    expect(chooseModel(DESKTOP_GPU)).toMatchObject({
      size: 'base',
      model: MODELS.base.id,
      device: 'webgpu',
      dtype: { encoder_model: 'fp32', decoder_model_merged: 'q4' },
    })
    expect(chooseModel(NO_GPU)).toMatchObject({
      size: 'base',
      device: 'wasm',
      dtype: { encoder_model: 'q8', decoder_model_merged: 'q8' },
      downloadMb: 77,
    })
  })

  it('uses fp16 encoder when shader-f16 is available', () => {
    expect(chooseModel({ ...DESKTOP_GPU, shaderF16: true }).dtype.encoder_model).toBe('fp16')
  })

  it('picks tiny on very low memory devices and honours explicit choices', () => {
    expect(chooseModel({ ...NO_GPU, deviceMemory: 2 }).size).toBe('tiny')
    expect(chooseModel(NO_GPU, 'small').model).toBe('onnx-community/whisper-small')
    expect(chooseModel(DESKTOP_GPU, 'tiny').size).toBe('tiny')
  })

  it('returns null (server fallback) when disabled or unsupported', () => {
    expect(chooseModel(DESKTOP_GPU, 'off')).toBeNull()
    expect(chooseModel({ ...NO_GPU, worker: false })).toBeNull()
    expect(chooseModel({ ...NO_GPU, wasm: false })).toBeNull()
    expect(chooseModel(NO_GPU, 'large')).toBeNull()
  })
})

describe('toSegments', () => {
  it('converts chunks to ordered millisecond segments within the recording', () => {
    const output = {
      text: '구도는 좋아요. 명암이 약해요.',
      chunks: [
        { timestamp: [0, 2.5], text: ' 구도는 좋아요.' },
        { timestamp: [2.4, 5.01], text: ' 명암이 약해요.' },
        { timestamp: [5.0, 6], text: '   ' },
        { timestamp: [6.2, null], text: ' 마무리해요.' },
      ],
    }
    expect(toSegments(output, 8000)).toEqual([
      { start_ms: 0, end_ms: 2500, text: '구도는 좋아요.' },
      { start_ms: 2400, end_ms: 5010, text: '명암이 약해요.' },
      { start_ms: 6200, end_ms: 8000, text: '마무리해요.' },
    ])
  })

  it('clamps timestamps past the end and keeps start order', () => {
    const output = {
      chunks: [
        { timestamp: [3, 4], text: 'a' },
        { timestamp: [1, 2], text: 'b' },
        { timestamp: [9, 12], text: 'c' },
      ],
    }
    expect(toSegments(output, 10000)).toEqual([
      { start_ms: 3000, end_ms: 4000, text: 'a' },
      { start_ms: 3000, end_ms: 3000, text: 'b' },
      { start_ms: 9000, end_ms: 10000, text: 'c' },
    ])
  })

  it('falls back to the full text and splits long text', () => {
    expect(toSegments({ text: ' 전체 ' }, 4000)).toEqual([
      { start_ms: 0, end_ms: 4000, text: '전체' },
    ])
    const long = toSegments({ chunks: [{ timestamp: [0, 1], text: 'ㄱ'.repeat(1500) }] }, 2000)
    expect(long.map((s) => s.text.length)).toEqual([1000, 500])
    expect(toSegments({ text: '' }, 1000)).toEqual([])
  })
})

describe('looksDegenerate', () => {
  it('flags repeated hallucinations', () => {
    const seg = (text) => ({ start_ms: 0, end_ms: 0, text })
    expect(looksDegenerate([seg('네'), seg('네'), seg('네'), seg('네')])).toBe(true)
    expect(looksDegenerate([seg('a'), seg('b'), seg('c'), seg('d')])).toBe(false)
    expect(looksDegenerate([seg('네'), seg('네')])).toBe(false)
  })
})

describe('withTimeout', () => {
  it('resolves null after the limit', async () => {
    expect(await withTimeout(new Promise(() => {}), 10)).toBeNull()
    expect(await withTimeout(Promise.resolve('ok'), 1000)).toBe('ok')
  })
})

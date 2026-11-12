import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// 브라우저 저장소·이벤트 흉내 (vitest는 node 환경)
function fakeBrowser() {
  const store = new Map()
  vi.stubGlobal('localStorage', {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  })
  const handlers = {}
  vi.stubGlobal('window', {
    addEventListener: (type, fn) => {
      handlers[type] = fn
    },
  })
  return { store, handlers }
}

const api = {
  requestTranscription: vi.fn(),
  saveBrowserTranscript: vi.fn(),
}
const stt = {
  resolvePlan: vi.fn(),
  transcribeBlob: vi.fn(),
  cancelBrowserStt: vi.fn(),
  releaseModelLater: vi.fn(),
  setSafety: vi.fn(),
}
vi.mock('../aiApi', () => api)
vi.mock('./browserStt', () => stt)

const PLAN = { size: 'base', model: 'onnx-community/whisper-base', device: 'webgpu' }
const RESULT = {
  segments: [{ start_ms: 0, end_ms: 1000, text: '구도가 좋아요.' }],
  model: PLAN.model,
  device: 'webgpu',
  durationMs: 1000,
  chunkCount: 1,
  timings: { transcribeMs: 10 },
}

async function load() {
  vi.resetModules()
  return import('./deviceJobs')
}

describe('deviceJobs', () => {
  let browser
  beforeEach(() => {
    browser = fakeBrowser()
    for (const fn of [...Object.values(api), ...Object.values(stt)]) fn.mockReset()
    stt.resolvePlan.mockResolvedValue(PLAN)
    api.requestTranscription.mockResolvedValue({ status: 'QUEUED' })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('creates a deferred backup, transcribes, saves and clears the device record', async () => {
    const jobs = await load()
    stt.transcribeBlob.mockImplementation(async (_blob, _plan, { onChunk }) => {
      onChunk({ index: 0, total: 1, bounds: [{ start: 0, end: 10 }], parts: [{ offsetMs: 0, segments: [] }] })
      expect(JSON.parse(browser.store.get('artmate.stt.active')).parts).toHaveLength(1)
      return RESULT
    })
    api.saveBrowserTranscript.mockResolvedValue({ summary_status: 'QUEUED' })

    const outcome = await jobs.startDeviceJob({ artworkId: 'a', recordingId: 'r', blob: 'BLOB', autoSummarize: true })
    expect(outcome).toBe('device')
    expect(api.requestTranscription).toHaveBeenCalledWith('a', 'r', {
      autoSummarize: true,
      deferSeconds: jobs.BACKUP_DEFER_SECONDS,
    })
    expect(api.saveBrowserTranscript).toHaveBeenCalledWith('a', 'r', RESULT, { autoSummarize: true })
    expect(jobs.getDeviceJob('r')).toMatchObject({ phase: 'done', summaryStatus: 'QUEUED' })
    expect(browser.store.has('artmate.stt.active')).toBe(false)
  })

  it('falls back to the server right away when the device fails', async () => {
    const jobs = await load()
    stt.transcribeBlob.mockRejectedValue(new Error('stalled'))
    const outcome = await jobs.startDeviceJob({ artworkId: 'a', recordingId: 'r', blob: 'BLOB' })
    expect(outcome).toBe('server')
    // 마지막 호출: 백업을 지금 처리하도록 (deferSeconds 0)
    expect(api.requestTranscription).toHaveBeenLastCalledWith('a', 'r', { autoSummarize: false, deferSeconds: 0 })
    expect(jobs.getDeviceJob('r')).toMatchObject({ phase: 'server', error: 'stalled' })
    expect(stt.releaseModelLater).toHaveBeenCalled()
  })

  it('keeps the finished transcript on the device when only saving fails', async () => {
    const jobs = await load()
    stt.transcribeBlob.mockImplementation(async (_b, _p, { onChunk }) => {
      onChunk({ index: 0, total: 1, bounds: [{ start: 0, end: 10 }], parts: [{ offsetMs: 0, segments: [] }] })
      return RESULT
    })
    api.saveBrowserTranscript.mockRejectedValue(Object.assign(new Error('net'), { code: 'NETWORK_ERROR' }))
    api.requestTranscription.mockRejectedValueOnce(Object.assign(new Error('x'), { code: 'NETWORK_ERROR' }))
    api.requestTranscription.mockRejectedValueOnce(Object.assign(new Error('x'), { code: 'NETWORK_ERROR' }))

    const outcome = await jobs.startDeviceJob({ artworkId: 'a', recordingId: 'r', blob: 'BLOB' })
    expect(outcome).toBe('failed')
    expect(jobs.getInterrupted('r')).toMatchObject({ done: 1, total: 1, crashed: false })
    expect(browser.store.has('artmate.stt.active')).toBe(true)

    // 다시 시도하면 남은 결과로 이어서 (resume 전달)
    api.requestTranscription.mockResolvedValue({ status: 'QUEUED' })
    api.saveBrowserTranscript.mockResolvedValue({ summary_status: 'NOT_REQUESTED' })
    await jobs.startDeviceJob({ artworkId: 'a', recordingId: 'r', blob: 'BLOB' })
    expect(stt.transcribeBlob.mock.calls.at(-1)[2].resume.parts).toHaveLength(1)
    expect(jobs.getInterrupted('r')).toBeNull()
  })

  it('detects a tab killed mid-transcription and stops using WebGPU on this device', async () => {
    browser.store.set(
      'artmate.stt.active',
      JSON.stringify({ recordingId: 'r', artworkId: 'a', device: 'webgpu', bounds: [1, 2, 3], parts: [{}] }),
    )
    const jobs = await load()
    expect(stt.setSafety).toHaveBeenCalledWith('wasm')
    expect(jobs.getInterrupted('r')).toEqual({ done: 1, total: 3, crashed: true, device: 'webgpu' })
    expect(jobs.getInterrupted('other')).toBeNull()
  })

  it('a normal page close (pagehide) is not treated as a crash', async () => {
    const jobs = await load()
    browser.store.set('artmate.stt.active', JSON.stringify({ recordingId: 'r', device: 'webgpu', parts: [] }))
    browser.handlers.pagehide()
    expect(JSON.parse(browser.store.get('artmate.stt.active')).unloading).toBe(true)
    stt.setSafety.mockReset()
    const reloaded = await load()
    expect(stt.setSafety).not.toHaveBeenCalled()
    expect(reloaded.getInterrupted('r')).toMatchObject({ crashed: false })
    expect(jobs).not.toBe(reloaded)
  })

  it('"서버에서 처리하기" cancels the device run and hands it to the server', async () => {
    const jobs = await load()
    let rejectRun
    stt.transcribeBlob.mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectRun = reject
        }),
    )
    stt.cancelBrowserStt.mockImplementation(() => rejectRun(new Error('cancelled')))
    const run = jobs.startDeviceJob({ artworkId: 'a', recordingId: 'r', blob: 'BLOB' })
    await vi.waitFor(() => expect(stt.transcribeBlob).toHaveBeenCalled())
    jobs.skipToServer('r')
    expect(await run).toBe('server')
    expect(stt.cancelBrowserStt).toHaveBeenCalled()
  })
})

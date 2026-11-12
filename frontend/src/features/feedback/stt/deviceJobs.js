// 기기(브라우저) 전사 작업 관리 (v0.9.3)
//
// - 화면(React 컴포넌트)과 분리된 앱 전역 상태: 녹음 화면 → 작품 화면 등으로 이동해도 변환은 계속된다.
// - 녹음은 항상 먼저 업로드한 뒤 변환한다 (변환 중 탭이 죽어도 녹음은 서버에 남음).
// - 변환하는 동안 서버에 "백업" 전사 작업을 미뤄서(run_after) 만들어 둔다.
//   기기 전사가 저장되면 백업은 자동 취소, 브라우저가 닫히면 서버가 이어서 처리한다.
// - 구간이 끝날 때마다 중간 결과를 이 기기(localStorage)에 기록 → 탭이 강제 종료돼도 이어서 변환.
//   변환 결과는 저장되면 바로 지운다.
// - 한 번에 한 녹음만 변환한다 (휴대폰 메모리).
import { requestTranscription, saveBrowserTranscript } from '../aiApi'
import {
  cancelBrowserStt,
  releaseModelLater,
  resolvePlan,
  setSafety,
  transcribeBlob,
} from './browserStt'

const ACTIVE_KEY = 'artmate.stt.active'
// 기기 변환이 끝나지 않고 브라우저가 닫혔을 때 서버가 이어받기까지 기다리는 시간
export const BACKUP_DEFER_SECONDS = 900

export const BUSY_PHASES = ['queued', 'preparing', 'transcribing', 'saving']

const jobs = new Map() // recordingId → 상태 객체 (바뀔 때마다 새 객체 → useSyncExternalStore)
const listeners = new Set()
let queue = Promise.resolve()

function readActive() {
  try {
    return JSON.parse(localStorage.getItem(ACTIVE_KEY) ?? 'null')
  } catch {
    return null
  }
}

function writeActive(value) {
  try {
    if (value) localStorage.setItem(ACTIVE_KEY, JSON.stringify(value))
    else localStorage.removeItem(ACTIVE_KEY)
  } catch {
    // 저장 공간이 없으면 중간 결과 없이 진행 (이어서 변환만 안 됨)
  }
}

/**
 * 앱을 열 때: 지난번 변환이 끝나지 않은 채 남아 있으면 "중단된 작업".
 * 페이지가 정상적으로 닫힐 때는 pagehide에서 unloading 표시를 남긴다. 표시 없이 사라졌으면
 * 탭이 강제 종료된 것(휴대폰 메모리 부족 등)으로 보고, WebGPU였다면 이 기기에서는 WASM만 쓴다.
 */
function detectInterrupted() {
  const marker = readActive()
  if (!marker?.recordingId) return null
  const crashed = !marker.unloading
  if (crashed && marker.device === 'webgpu') setSafety('wasm')
  return { ...marker, crashed }
}

let interrupted = typeof window === 'undefined' ? null : detectInterrupted()

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => {
    const marker = readActive()
    if (marker) writeActive({ ...marker, unloading: true })
  })
  window.addEventListener('pageshow', (event) => {
    // 뒤로 가기 캐시(bfcache)로 돌아옴 → 작업이 그대로 살아 있음
    if (!event.persisted) return
    const marker = readActive()
    if (marker?.unloading) writeActive({ ...marker, unloading: false })
  })
  // 변환 중 새로고침·닫기를 누르면 브라우저 확인 창 (실수로 처음부터 다시 하지 않도록)
  window.addEventListener('beforeunload', (event) => {
    if (hasBusyDeviceJob()) {
      event.preventDefault()
      event.returnValue = ''
    }
  })
}

function emit() {
  for (const listener of listeners) listener()
}

function update(recordingId, patch) {
  const prev = jobs.get(recordingId) ?? {}
  jobs.set(recordingId, { ...prev, ...(typeof patch === 'function' ? patch(prev) : patch) })
  emit()
}

export function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 다른 녹음을 변환 중인지 (그동안 Worker를 닫으면 안 됨) */
export function hasBusyDeviceJob() {
  return [...jobs.values()].some((job) => BUSY_PHASES.includes(job.phase))
}

export function getDeviceJob(recordingId) {
  return jobs.get(recordingId) ?? null
}

/** 지난번에 이 녹음 변환이 중간에 끊겼으면 { done, total, crashed } */
export function getInterrupted(recordingId) {
  if (interrupted?.recordingId !== recordingId) return null
  return {
    done: interrupted.parts?.length ?? 0,
    total: interrupted.bounds?.length ?? null,
    crashed: interrupted.crashed,
    device: interrupted.device,
  }
}

export function forgetInterrupted(recordingId) {
  if (interrupted?.recordingId !== recordingId) return
  interrupted = null
  const marker = readActive()
  if (marker?.recordingId === recordingId && !jobs.has(recordingId)) writeActive(null)
  emit()
}

/**
 * 기기 전사 시작 (이미 진행 중이면 그 작업). 결과를 기다릴 필요 없다 — 상태는 subscribe로 본다.
 * blob 또는 getBlob(저장된 녹음을 다시 받기) 중 하나.
 * autoSummarize: 저장할 때 AI 정리도 요청 (AI 전송 동의가 있을 때만 서버가 만든다)
 * → Promise<'device' | 'server' | 'failed'>
 */
export function startDeviceJob({ artworkId, recordingId, blob, getBlob, autoSummarize = false }) {
  const current = jobs.get(recordingId)
  if (current && BUSY_PHASES.includes(current.phase)) return current.promise
  const run = queue.then(() => runJob({ artworkId, recordingId, blob, getBlob, autoSummarize }))
  queue = run.catch(() => {})
  update(recordingId, {
    phase: 'queued',
    artworkId,
    plan: null,
    progress: null,
    chunk: null,
    error: null,
    summaryStatus: null,
    promise: run,
  })
  return run
}

/** "서버에서 처리하기": 기기 변환을 멈추면 runJob이 서버 처리로 넘긴다 */
export function skipToServer(recordingId) {
  const current = jobs.get(recordingId)
  if (!current || !BUSY_PHASES.includes(current.phase)) return
  update(recordingId, { skipped: true })
  if (current.phase === 'queued') return // 차례가 오면 바로 서버로
  cancelBrowserStt()
}

async function requestServer(artworkId, recordingId, autoSummarize, deferSeconds = 0) {
  try {
    await requestTranscription(artworkId, recordingId, { autoSummarize, deferSeconds })
    return 'server'
  } catch (err) {
    if (err?.code === 'TRANSCRIPTION_ALREADY_DONE') return 'device'
    return 'failed'
  }
}

async function runJob({ artworkId, recordingId, blob, getBlob, autoSummarize }) {
  const resume =
    interrupted?.recordingId === recordingId && interrupted.parts?.length
      ? { bounds: interrupted.bounds, parts: interrupted.parts }
      : null
  let saveFailed = false
  try {
    const plan = jobs.get(recordingId)?.skipped ? null : await resolvePlan()
    if (!plan) {
      const outcome = await requestServer(artworkId, recordingId, autoSummarize)
      update(recordingId, { phase: outcome === 'failed' ? 'failed' : outcome === 'device' ? 'done' : 'server' })
      return outcome
    }
    update(recordingId, { phase: 'preparing', plan })
    // 백업: 이 기기 변환이 끝나지 못하면(브라우저 종료 등) 서버가 이어서 처리. 서버 변환이 꺼져 있으면 무시
    await requestServer(artworkId, recordingId, autoSummarize, BACKUP_DEFER_SECONDS)

    const marker = {
      recordingId,
      artworkId,
      device: plan.device,
      size: plan.size,
      startedAt: Date.now(),
      bounds: resume?.bounds ?? null,
      parts: resume?.parts ?? [],
    }
    writeActive(marker)
    const audioBlob = blob ?? (await getBlob())
    const result = await transcribeBlob(audioBlob, plan, {
      resume,
      onStage: (stage, info) =>
        update(recordingId, (prev) => ({
          phase: stage === 'transcribing' ? 'transcribing' : 'preparing',
          chunk: info ? { done: info.done, total: info.chunkCount } : prev.chunk,
        })),
      onProgress: (progress) => update(recordingId, { progress }),
      onFallback: () => {
        update(recordingId, { fellBack: true })
        writeActive({ ...readActive(), device: 'wasm' })
      },
      onChunk: ({ index, total, bounds, parts }) => {
        update(recordingId, { chunk: { done: index + 1, total } })
        writeActive({ ...marker, ...readActive(), bounds, parts, unloading: false })
      },
    })

    update(recordingId, { phase: 'saving' })
    let summaryStatus = null
    try {
      const saved = await saveBrowserTranscript(artworkId, recordingId, result, { autoSummarize })
      summaryStatus = saved?.summary_status ?? null
    } catch (err) {
      // 서버가 먼저 전사했으면 그 결과를 쓴다
      if (err?.code !== 'TRANSCRIPTION_ALREADY_DONE') {
        // 저장만 실패(네트워크 등): 변환 결과는 이 기기에 남겨 "이어서 변환"으로 다시 저장 (재변환 없음)
        saveFailed = true
        throw err
      }
    }
    writeActive(null)
    if (interrupted?.recordingId === recordingId) interrupted = null
    update(recordingId, {
      phase: 'done',
      summaryStatus,
      result: {
        device: result.device,
        model: result.model,
        durationMs: result.durationMs,
        chunkCount: result.chunkCount,
        timings: result.timings,
      },
    })
    return 'device'
  } catch (error) {
    // 기기 변환 실패·중단·시간 초과·저장 실패 → 백업 서버 작업을 바로 처리하도록 앞당김
    if (saveFailed) {
      interrupted = { ...readActive(), crashed: false }
    } else {
      writeActive(null)
      if (interrupted?.recordingId === recordingId) interrupted = null
    }
    const outcome = await requestServer(artworkId, recordingId, autoSummarize)
    update(recordingId, {
      phase: outcome === 'device' ? 'done' : outcome,
      error: String(error?.message ?? error).slice(0, 100),
    })
    return outcome
  } finally {
    releaseModelLater()
  }
}

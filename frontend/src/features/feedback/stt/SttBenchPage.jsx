import { useEffect, useState } from 'react'
import { detectCapabilities, resolvePlan, transcribeBlob } from './browserStt'
import { PREFERENCES, chooseModel } from './models'
import { analyzeBlob, judgeSignal } from '../audioSignal'
import { cer, termAccuracy } from './sttMetrics'

const SIGNAL_LABEL = { silent: '거의 무음', quiet: '소리 작음', ok: '정상' }

// ?device=wasm 이면 WebGPU가 있어도 WASM으로 측정
const FORCE_WASM = new URLSearchParams(window.location.search).get('device') === 'wasm'

/**
 * 기기 음성 인식 성능 측정 (/tools/stt-bench). 로그인 불필요.
 * 고른 녹음 파일을 이 기기 안에서만 변환하고 시간을 보여 준다 (서버로 아무것도 보내지 않음).
 * 측정 결과는 window.__sttBench에도 남긴다 (자동 측정 스크립트용).
 */
export default function SttBenchPage() {
  const [caps, setCaps] = useState(null)
  const [preference, setPreference] = useState('auto')
  const [runs, setRuns] = useState([])
  const [busy, setBusy] = useState('')
  const [reference, setReference] = useState('') // 정답 대본 (있으면 CER·미술 용어 정확도 계산)

  useEffect(() => {
    detectCapabilities().then(setCaps)
  }, [])

  async function run(file) {
    const plan = FORCE_WASM
      ? chooseModel({ ...(await detectCapabilities()), webgpu: false }, preference)
      : await resolvePlan(preference)
    if (!plan) {
      setBusy('이 기기·설정에서는 기기 음성 인식을 쓸 수 없어요.')
      return
    }
    setBusy('녹음 신호 확인 중…')
    // 재생·STT 문제 진단: 파일에 실제 소리가 있는지 (기기 안에서만)
    const signal = await analyzeBlob(file, { maxMs: 20 * 60 * 1000 })
    setBusy('준비 중…')
    try {
      const result = await transcribeBlob(file, plan, {
        onStage: (stage) => setBusy(stage === 'transcribing' ? '변환 중…' : '모델 불러오는 중…'),
        onChunk: ({ index, total }) => setBusy(`변환 중… ${index + 1}/${total} 구간`),
        onProgress: (p) => p.total && setBusy(`모델 다운로드 ${Math.round((p.loaded / p.total) * 100)}%`),
      })
      const entry = {
        file: file.name,
        model: plan.size,
        device: result.device, // WebGPU 초기화 실패 시 WASM으로 바뀐 실제 장치
        audioS: (result.durationMs / 1000).toFixed(1),
        chunkCount: result.chunkCount,
        ...result.timings,
        text: result.segments.map((s) => s.text).join(' '),
        signal,
        signalJudge: signal ? judgeSignal(signal) : null,
        memoryMb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null,
      }
      if (reference.trim()) {
        entry.cer = cer(reference, entry.text)
        entry.terms = termAccuracy(reference, entry.text)
      }
      window.__sttBench = [...(window.__sttBench ?? []), entry]
      setRuns((prev) => [...prev, entry])
      setBusy('')
    } catch (error) {
      window.__sttBench = [...(window.__sttBench ?? []), { file: file.name, error: error.message, signal }]
      setBusy(`실패: ${error.message}`)
    }
  }

  return (
    <main style={{ padding: 16, maxWidth: 720, margin: '0 auto', fontSize: 14 }}>
      <h1 style={{ fontSize: 20 }}>기기 음성 인식 측정</h1>
      <p>녹음 파일은 이 기기 밖으로 나가지 않습니다. 처음에는 모델을 내려받습니다.</p>
      <pre data-testid="caps">{caps ? JSON.stringify(caps) : '확인 중…'}</pre>
      <label>
        모델{' '}
        <select value={preference} onChange={(e) => setPreference(e.target.value)} data-testid="pref">
          {PREFERENCES.filter((p) => p !== 'off').map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </label>{' '}
      <input
        type="file"
        accept="audio/*"
        data-testid="file"
        disabled={Boolean(busy && !busy.startsWith('실패'))}
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (file) run(file)
        }}
      />
      <label style={{ display: 'block', marginTop: 8 }}>
        정답 대본 (선택, 붙여 넣으면 정확도 계산)
        <textarea
          data-testid="reference"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          rows={3}
          style={{ width: '100%' }}
        />
      </label>
      <p data-testid="busy">{busy}</p>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            {['파일', '모델', '장치', '음성(초)', '모델 로드', '메모리 재사용', '변환', '전체'].map((h) => (
              <th key={h} style={{ textAlign: 'left', borderBottom: '1px solid #ccc' }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r, i) => (
            <tr key={i}>
              <td>{r.file}</td>
              <td>{r.model}</td>
              <td>{r.device}</td>
              <td>{r.audioS}</td>
              <td>{(r.loadMs / 1000).toFixed(1)}s</td>
              <td>{r.modelReused ? '예' : '아니오'}</td>
              <td>{(r.transcribeMs / 1000).toFixed(1)}s</td>
              <td>{(r.totalMs / 1000).toFixed(1)}s</td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs.map((r, i) => (
        <div key={i} style={{ marginTop: 12 }}>
          <p>
            <b>{r.file}</b> · 신호:{' '}
            {r.signal
              ? `${SIGNAL_LABEL[r.signalJudge]} (최대 ${r.signal.peak}, ${r.signal.rmsDb}dB, 소리 구간 ${Math.round(r.signal.speechRatio * 100)}%)`
              : '확인 못 함'}
            {r.skippedChunks ? ` · 무음 구간 ${r.skippedChunks}개 건너뜀` : ''}
            {r.cer != null && ` · CER ${(r.cer * 100).toFixed(1)}%`}
            {r.terms?.ratio != null &&
              ` · 미술 용어 ${r.terms.matched}/${r.terms.total}${r.terms.missed.length ? ` (놓침: ${r.terms.missed.join(', ')})` : ''}`}
          </p>
          <p style={{ whiteSpace: 'pre-wrap' }}>{r.text}</p>
        </div>
      ))}
    </main>
  )
}

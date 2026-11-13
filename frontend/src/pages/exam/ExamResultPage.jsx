import { useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import FullScreenStatus from '../../components/layout/FullScreenStatus'
import { Button, Card } from '../../components/ui'
import { getArtwork, getExam, listArtworks } from '../../features/artworks/api'
import {
  examStageName,
  formatDurationSeconds,
  formatMinutes,
  stageOfNote,
} from '../../features/artworks/exam'
import { listNotes } from '../../features/feedback/notesApi'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './Exam.module.css'

async function loadResult(artworkId) {
  const [artwork, exam, notes] = await Promise.all([
    getArtwork(artworkId),
    getExam(artworkId),
    listNotes(artworkId),
  ])
  // 직전 시험: 같은 실기 유형의 모의시험 중 이 작품 말고, 소요 시간이 기록된 가장 최근 것
  // (유형이 다르면 제한 시간·작업 방식이 달라 비교 의미가 약함. 유형 미선택이면 미선택끼리)
  const exams = await listArtworks({
    limit: 20,
    workCategory: 'MOCK_EXAM',
    practicalType: artwork.practical_type ?? undefined,
  })
  const previous = exams.items.find(
    (a) =>
      a.id !== artworkId &&
      a.actual_minutes &&
      (a.practical_type ?? null) === (artwork.practical_type ?? null),
  )
  return { artwork, exam, notes, previous }
}

/** 실기시험 결과 (/artworks/:artworkId/exam/result) */
export default function ExamResultPage() {
  const { artworkId } = useParams()
  const navigate = useNavigate()
  const options = useOptions()
  const load = useCallback(() => loadResult(artworkId), [artworkId])
  const { data, error, reload } = useAsync(load)

  if (error) {
    return (
      <FullScreenStatus title="결과를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!data) return <FullScreenStatus />

  const { artwork, exam, notes, previous } = data
  const typeLabel =
    artwork.practical_type && options
      ? labelOf(options.practical_types, artwork.practical_type)
      : null
  const stages = exam.stages.filter((s) => s.started_at) // 시작한 단계만 (중간에 끝내면 뒤 단계는 없음)
  // 끝난 시험은 타이머의 누적 초, 아니면 작품에 저장된 분
  const totalSeconds =
    exam.timer.state === 'STOPPED' ? exam.timer.elapsed_seconds : (artwork.actual_minutes ?? 0) * 60
  const limitMinutes = artwork.time_limit_minutes ?? exam.total_target_minutes
  const notesByStage = {}
  const otherNotes = []
  // v0.9.7: 단계에 연결된 메모는 그 단계로 (시험 단계 i = 작품 단계 i), 아니면 작성 시각으로
  const plan = artwork.stage_plan ?? []
  const codeOfStageId = (id) => {
    const i = plan.length === exam.stages.length ? plan.findIndex((p) => p.id === id) : -1
    return i >= 0 ? exam.stages[i].stage : null
  }
  for (const n of notes) {
    const stage = (n.stage_id && codeOfStageId(n.stage_id)) || stageOfNote(stages, n)
    if (stage) (notesByStage[stage] ??= []).push(n)
    else otherNotes.push(n)
  }

  return (
    <main className={styles.body}>
      <div className={styles.resultHead}>
        <span className={styles.eyebrow}>시험 기록 완료</span>
        <h1 className={styles.resultTitle}>{artwork.title}</h1>
        <p className={styles.lead}>
          단계별 작업 시간과 사진·피드백을 하나의 기록으로 정리했습니다.
        </p>
      </div>

      <div className={styles.stats}>
        <Card className={styles.stat}>
          <span className={styles.small}>전체 실제 시간</span>
          <strong className={styles.statValue}>{formatDurationSeconds(totalSeconds)}</strong>
        </Card>
        <Card className={styles.stat}>
          <span className={styles.small}>설정한 목표</span>
          <strong className={styles.statValue}>
            {limitMinutes ? formatMinutes(limitMinutes) : '-'}
          </strong>
        </Card>
      </div>

      <Card className={styles.section}>
        <h2 className={styles.cardTitle}>직전 시험과 비교</h2>
        {typeLabel && (
          <span className={styles.small}>같은 실기 유형({typeLabel}) 시험끼리 비교해요</span>
        )}
        <p className={styles.muted}>
          {previous
            ? `${previous.title}: ${formatMinutes(previous.actual_minutes)} → 이번 ${formatDurationSeconds(totalSeconds)} (${compare(previous.actual_minutes * 60, totalSeconds)})`
            : `${typeLabel ? `${typeLabel} ` : ''}첫 시험 기록입니다. 다음 시험을 완료하면 소요 시간 변화를 비교할 수 있습니다.`}
        </p>
      </Card>

      <section className={styles.section}>
        <h2 className={styles.heading}>단계별 진행 결과</h2>
        {stages.length ? (
          stages.map((t, i) => (
            <Card key={t.stage} className={styles.section}>
              <div className={styles.stageHead}>
                <strong>
                  {i + 1}. {examStageName(artwork, exam.stages, i)}
                </strong>
                <span className={`${styles.stageTime} ${t.over_target ? styles.overText : ''}`}>
                  실제 {formatDurationSeconds(t.elapsed_seconds)} / 목표{' '}
                  {formatMinutes(t.target_minutes)}
                </span>
              </div>
              {notesByStage[t.stage]?.length ? (
                notesByStage[t.stage].map((n) => (
                  <p key={n.id} className={styles.noteText}>
                    {n.body}
                  </p>
                ))
              ) : (
                <p className={styles.muted}>입력한 피드백·메모가 없습니다.</p>
              )}
            </Card>
          ))
        ) : (
          <Card variant="soft">
            이 시험은 단계 기록 없이 진행돼 전체 시간만 있어요. 메모는 아래에 모두 저장돼 있어요.
          </Card>
        )}
        {otherNotes.length > 0 && (
          <Card className={styles.section}>
            <strong>{stages.length ? '그 밖의 메모' : '메모'}</strong>
            {otherNotes.map((n) => (
              <p key={n.id} className={styles.noteText}>
                {n.body}
              </p>
            ))}
          </Card>
        )}
      </section>

      <div className={styles.buttons}>
        <Button variant="soft" className={styles.outline} onClick={() => navigate('/practice')}>
          실기 메인으로
        </Button>
        <Button onClick={() => navigate(`/artworks/${artwork.id}`)}>저장된 작품 상세</Button>
      </div>
    </main>
  )
}

/** 이전·이번 소요 시간 차이 (빨라짐/늘어남은 시간만 비교, 실력 평가 아님) */
function compare(prevSeconds, nowSeconds) {
  const diff = nowSeconds - prevSeconds
  if (Math.abs(diff) < 60) return '비슷해요'
  return `${formatDurationSeconds(Math.abs(diff))} ${diff < 0 ? '단축' : '늘어남'}`
}

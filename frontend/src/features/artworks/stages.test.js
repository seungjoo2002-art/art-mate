import { describe, expect, it } from 'vitest'
import { targetsFromPlan } from './exam'
import {
  newStageRow,
  revisionPhotosOf,
  stageListError,
  stagesWithPhotos,
  toStageSpecs,
  unlinkedRevisions,
} from './stages'

const plan = [
  { id: 's1', name: '아이디어', position: 0, legacy_stage: 'SKETCH', target_minutes: 20 },
  { id: 's2', name: '밑색', position: 1, legacy_stage: 'PROGRESS', target_minutes: null },
  { id: 's3', name: '묘사', position: 2, legacy_stage: 'PROGRESS', target_minutes: null },
  { id: 's4', name: '마무리', position: 3, legacy_stage: 'FINAL', target_minutes: 40 },
]

const photo = (id, extra) => ({
  id,
  kind: 'STAGE',
  is_representative: false,
  uploaded_at: '2026-11-13T01:00:00Z',
  ...extra,
})

describe('stagesWithPhotos', () => {
  it('uses the custom stage plan and representative stage photos only', () => {
    const artwork = {
      stage_plan: plan,
      stages: [],
      photos: [
        photo('p1', { stage_id: 's2', is_representative: true }),
        photo('p2', { stage_id: 's2' }),
        photo('r1', { stage_id: 's2', kind: 'REVISION', feedback_note_id: 'n1' }),
      ],
    }
    const stages = stagesWithPhotos(artwork)
    expect(stages.map((s) => s.label)).toEqual(['아이디어', '밑색', '묘사', '마무리'])
    expect(stages[1].photo.id).toBe('p1')
    expect(stages[1].photoLabel).toBe('밑색 사진')
    expect(stages[0].photo).toBeNull()
    expect(stages[0].targetMinutes).toBe(20)
  })

  it('falls back to the legacy fixed stages for old responses', () => {
    const artwork = {
      stages: [{ stage: 'FINAL', representative_photo_id: 'p9', last_uploaded_at: 'x' }],
      photos: [photo('p9', { stage: 'FINAL' })],
    }
    const stages = stagesWithPhotos(artwork)
    expect(stages.map((s) => s.legacy)).toEqual(['SKETCH', 'PROGRESS', 'FINAL'])
    expect(stages[2].photo.id).toBe('p9')
    expect(stages.every((s) => s.id === null)).toBe(true)
  })
})

describe('revision photos', () => {
  const artwork = {
    photos: [
      photo('r2', {
        kind: 'REVISION',
        stage_id: 's1',
        feedback_note_id: 'n1',
        uploaded_at: '2026-11-13T03:00:00Z',
      }),
      photo('r1', {
        kind: 'REVISION',
        stage_id: 's1',
        feedback_note_id: 'n1',
        uploaded_at: '2026-11-13T02:00:00Z',
      }),
      photo('r3', { kind: 'REVISION', stage_id: 's1', feedback_recording_id: 'rec1' }),
      photo('r4', { kind: 'REVISION', stage_id: 's1' }),
      photo('p1', { stage_id: 's1' }),
    ],
  }

  it('groups revision photos by feedback in upload order', () => {
    expect(revisionPhotosOf(artwork, { type: 'NOTE', id: 'n1' }).map((p) => p.id)).toEqual([
      'r1',
      'r2',
    ])
    expect(revisionPhotosOf(artwork, { type: 'RECORDING', id: 'rec1' }).map((p) => p.id)).toEqual([
      'r3',
    ])
  })

  it('keeps revisions whose feedback was deleted', () => {
    expect(unlinkedRevisions(artwork, 's1').map((p) => p.id)).toEqual(['r4'])
  })
})

describe('stage editing', () => {
  it('validates count, names and exam minutes', () => {
    expect(stageListError([])).toMatch(/1개 이상/)
    expect(stageListError(Array.from({ length: 11 }, () => newStageRow('a')))).toMatch(/10개/)
    expect(stageListError([newStageRow('  ')])).toMatch(/이름/)
    expect(stageListError([newStageRow('가'.repeat(31))])).toMatch(/30자/)
    expect(stageListError([newStageRow('a')], { withMinutes: true })).toMatch(/목표 시간/)
    expect(stageListError([newStageRow('a', { minutes: 10 })], { withMinutes: true })).toBe('')
  })

  it('builds the request body keeping ids of existing stages', () => {
    const rows = [
      { key: 's1', id: 's1', name: ' 스케치 ', minutes: 30 },
      newStageRow('채색', { minutes: 60 }),
    ]
    expect(toStageSpecs(rows)).toEqual([{ id: 's1', name: '스케치' }, { name: '채색' }])
    expect(toStageSpecs(rows, { withMinutes: true })).toEqual([
      { id: 's1', name: '스케치', target_minutes: 30 },
      { name: '채색', target_minutes: 60 },
    ])
  })
})

describe('targetsFromPlan', () => {
  it('splits the remaining limit over stages without a target', () => {
    const targets = targetsFromPlan({ stage_plan: plan, time_limit_minutes: 200 })
    expect(targets.map((t) => [t.label, t.minutes, t.stageId])).toEqual([
      ['아이디어', 20, 's1'],
      ['밑색', 70, 's2'],
      ['묘사', 70, 's3'],
      ['마무리', 40, 's4'],
    ])
  })

  it('returns null for old responses', () => {
    expect(targetsFromPlan({})).toBeNull()
  })
})

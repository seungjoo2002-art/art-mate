import { describe, expect, it } from 'vitest'
import { artworkStageFor, examStageName, rowsToPlan } from './exam'
import {
  newStageRow,
  stageListError,
  stagePhotos,
  stagesWithPhotos,
  toStageSpecs,
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

describe('stagePhotos (v0.9.8 timeline)', () => {
  it('lists every active photo of the stage in upload order, old revisions included', () => {
    const artwork = {
      photos: [
        photo('p2', { stage_id: 's1', status: 'ACTIVE', uploaded_at: '2026-11-13T02:00:00Z' }),
        photo('r1', {
          stage_id: 's1',
          kind: 'REVISION',
          status: 'ACTIVE',
          feedback_note_id: 'n1',
          uploaded_at: '2026-11-13T03:00:00Z',
        }),
        photo('p1', { stage_id: 's1', status: 'ACTIVE', uploaded_at: '2026-11-13T01:00:00Z' }),
        photo('d1', { stage_id: 's1', status: 'DELETED' }),
        photo('x1', { stage_id: 's2', status: 'ACTIVE' }),
      ],
    }
    expect(stagePhotos(artwork, 's1').map((p) => p.id)).toEqual(['p1', 'p2', 'r1'])
    expect(stagePhotos(artwork, null)).toHaveLength(4)
  })

  it('lets a photo taken after feedback be the stage representative', () => {
    const artwork = {
      stage_plan: plan.slice(0, 1),
      photos: [
        photo('p1', { stage_id: 's1' }),
        photo('r1', { stage_id: 's1', kind: 'REVISION', is_representative: true }),
      ],
    }
    expect(stagesWithPhotos(artwork)[0].photo.id).toBe('r1')
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

describe('exam stages ↔ artwork stages', () => {
  const exam = [
    { stage: 'IDEA', label: '아이디어' },
    { stage: 'SKETCH', label: '스케치' },
    { stage: 'COLOR', label: '채색' },
    { stage: 'FINISH', label: '마무리' },
  ]

  it('assigns exam codes by position', () => {
    expect(
      rowsToPlan([
        { name: '구상', minutes: 30 },
        { name: '묘사', minutes: 90 },
      ]),
    ).toEqual([
      { stage: 'IDEA', target_minutes: 30 },
      { stage: 'SKETCH', target_minutes: 90 },
    ])
  })

  it('maps exam stage i to artwork stage i with the custom name', () => {
    const artwork = { stage_plan: plan }
    expect(artworkStageFor(artwork, exam, 1).id).toBe('s2')
    expect(examStageName(artwork, exam, 3)).toBe('마무리')
    expect(examStageName(artwork, exam, 1)).toBe('밑색')
  })

  it('falls back to server labels when counts differ (old exams)', () => {
    const artwork = { stage_plan: plan.slice(0, 3) }
    expect(artworkStageFor(artwork, exam, 0)).toBeNull()
    expect(examStageName(artwork, exam, 0)).toBe('아이디어')
    expect(examStageName({}, exam, 2)).toBe('채색')
  })
})

// 아카이브 작품 분류·작품 카드 문구 (순수 함수)
// 분류는 서버의 실제 필드(work_category)로만 한다. 제목·시간 제한으로 추측하지 않는다.

import { isCompleted } from './stages'

/**
 * 아카이브 최상위 분류
 * - exam: 실기시험 모드로 만든 작품 (work_category = MOCK_EXAM, 서버 필터)
 * - mock: 실기 모의고사 (대학·학과·연도·전형 기출). 서버에 구분할 필드가 아직 없어 분류하지 않음
 * - record: 실기시험이 아닌 작품 (자유 기록·개인 연습·수업 작품, work_category ≠ MOCK_EXAM)
 */
export const ARCHIVE_KINDS = [
  { code: '', label: '전체' },
  { code: 'exam', label: '실기시험' },
  { code: 'mock', label: '실기 모의고사' },
  { code: 'record', label: '내 작품 기록' },
]

export const archiveKind = (value) =>
  ARCHIVE_KINDS.some((k) => k.code === value) ? value : ''

/** 서버 목록 요청 조건. mock은 요청하지 않음(null) */
export function archiveQuery(kind) {
  if (kind === 'mock') return null
  if (kind === 'exam') return { workCategory: 'MOCK_EXAM' }
  return {}
}

/** 받은 목록에서 화면에 보여 줄 작품 (record만 화면에서 거름 — 서버에 'MOCK_EXAM 아님' 필터가 없음) */
export function archiveItems(kind, items) {
  if (kind === 'record') return items.filter((a) => a.work_category !== 'MOCK_EXAM')
  return items
}

/** 분류별 빈 화면 문구 */
export const ARCHIVE_EMPTY = {
  '': ['아직 기록한 작품이 없어요', '실기 탭에서 작품을 기록하면 이곳에 차곡차곡 모여요.'],
  exam: ['아직 실기시험 기록이 없어요', '시간을 재며 그린 작품이 이곳에 모여요.'],
  mock: [
    '실기 모의고사는 준비하고 있어요',
    '대학별 기출 주제로 그린 작품은 기능이 열리면 이곳에 모여요.',
  ],
  record: ['아직 자유롭게 기록한 작품이 없어요', '새 작품 기록으로 첫 그림을 남겨 보세요.'],
}

/**
 * 작품 카드 문구
 * - 상태: 완성 / 그리는 중
 * - 실기시험 표시 (작업 목적이 MOCK_EXAM일 때만)
 * - 사진 없음: 진행 중이면 "그리면서 사진을 남겨 보세요", 완성이면 "작품 사진을 등록해 주세요"
 */
export function artworkCardView(artwork) {
  const done = isCompleted(artwork)
  return {
    status: done ? '완성' : '그리는 중',
    done,
    exam: artwork.work_category === 'MOCK_EXAM',
    hasPhoto: Boolean(artwork.cover_photo_id),
    emptyHint: done ? '작품 사진을 등록해 주세요' : '그리면서 사진을 남겨 보세요',
  }
}

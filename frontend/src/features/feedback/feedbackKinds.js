// 첨삭 항목 종류: API 필드명과 기본 라벨 (라벨은 /meta/options의 feedback_item_kinds가 있으면 그걸 씀)
export const KINDS = [
  { kind: 'STRENGTH', field: 'strengths', label: '잘한 점' },
  { kind: 'WEAKNESS', field: 'weaknesses', label: '부족한 점' },
  { kind: 'FIX', field: 'fixes', label: '수정 방법' },
  { kind: 'NEXT_TIP', field: 'next_tips', label: '다음 작품 주의점' },
]

export const ORIGIN_LABELS = { EDITED: '수정함', ADDED: '직접 추가' }

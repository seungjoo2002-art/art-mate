// v1.2 녹음 대본의 STT 원문·AI 문맥 보정 비교 (GET …/transcript의 stt_original·ai_correction)
// 서버가 보정본을 새 행으로 저장하고 원문을 보존한다. 화면은 받은 값만 비교해서 보여 준다.

/**
 * 반환
 * - aiChanged: AI가 바꾼 구간 번호 Set (없으면 빈 Set)
 * - differs: 지금 대본과 STT 원문이 다른 구간 번호 Set (AI 보정 + 학생 수정)
 * - originalText(index): 그 구간의 STT 원문 (원문과 같거나 원문이 없으면 null)
 * - notice: AI 보정 안내 문구 (보정 없으면 null)
 * - hasOriginal: '원본 STT 보기'를 보여 줄지
 */
export function correctionView(transcript) {
  const original = transcript?.stt_original ?? null
  const correction = transcript?.ai_correction ?? null
  const byIndex = new Map((original?.segments ?? []).map((s) => [s.index, s.text]))
  const differs = new Set(original?.differs_from_current ?? [])
  return {
    aiChanged: new Set(correction?.changed_segments ?? []),
    differs,
    originalText: (index) => (differs.has(index) ? (byIndex.get(index) ?? null) : null),
    notice: correction?.notice ?? null,
    hasOriginal: differs.size > 0,
  }
}

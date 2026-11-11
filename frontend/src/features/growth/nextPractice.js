// 분석 리포트 탭 "다음 학습 우선순위"와 홈 "오늘의 추천 연습"이 같이 쓰는 규칙 (AI 아님)

const ACTIVE = ['ADOPTED', 'IN_REVIEW', 'DRAFT']

/** 진행 중인 맞춤 연습 과제 → 다음 연습 목표 → 첫 기록 안내 */
export function pickNextPractice(analysis, recommendations) {
  const rec = recommendations
    .filter((r) => ACTIVE.includes(r.status))
    .sort((a, b) => ACTIVE.indexOf(a.status) - ACTIVE.indexOf(b.status))[0]
  if (rec) {
    return {
      label: `맞춤 연습 과제 · ${rec.status === 'ADOPTED' ? '진행 중' : '새 추천'}`,
      title: rec.title,
      goal: rec.learning_goal || rec.description,
      method: rec.method_steps?.join(' → '),
      category: rec.weakness_category,
      action: '추천 연습 이어서 하기',
      to: `/growth/recommendations/${rec.id}`,
    }
  }
  const goal = analysis.next_goals?.[0]
  if (goal) {
    return {
      label: '누적 첨삭 기반 제안',
      title: goal.goal,
      goal: '반복해서 지적된 항목을 다음 작품에서 의식적으로 점검해 보세요.',
      method: '맞춤 연습 과제를 받아 짧게 연습한 뒤 작품에 적용해 보세요.',
      category: goal.category,
      action: '맞춤 연습 과제 받기',
      to: '/growth/recommendations',
    }
  }
  return {
    label: '첫 기록 · 기록 기반 제안',
    title: '첫 작품의 제작 과정 기록하기',
    goal: '단계별 사진과 간단한 첨삭부터 저장해 보세요.',
    method: '사진 1장과 메모 1개부터 시작해도 괜찮습니다.',
    category: null,
    action: '연습 시작 · 작품 기록',
    to: '/artworks/new',
  }
}

/** 가장 많이 지적된 약점·강점으로 만든 한 줄 요약 (분석 가능할 때만) */
export function summaryLine(analysis) {
  if (analysis.status !== 'READY') {
    return '피드백 기록이 쌓이면 반복되는 항목과 변화 흐름을 확인할 수 있습니다.'
  }
  const top = analysis.weaknesses.find((w) => w.category === analysis.top_weaknesses[0])
  const strength = analysis.strengths?.[0]
  if (!top && !strength) return '아직 반복해서 언급된 항목이 없어요.'
  const parts = []
  if (top) parts.push(`최근 첨삭에서 '${top.label}'이(가) 가장 자주 언급됐어요`)
  if (strength) parts.push(`'${strength.label}'은(는) 긍정적으로 언급됐어요`)
  return `${parts.join(', ')}.`
}

/** 모의시험 작품 수 */
export const mockExamCount = (analysis) =>
  analysis.work_category_distribution?.find((d) => d.work_category === 'MOCK_EXAM')
    ?.artwork_count ?? 0

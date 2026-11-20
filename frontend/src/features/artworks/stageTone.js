/**
 * 단계 물감 색: 첫 단계는 연한 주황 → 가운데 주황 → 마지막 단계는 진한 갈주황 (그림이 채워질수록 진해짐)
 * 제작 단계 길(StagePath), 시험 단계 원형 시계(ExamStagePlanner)가 같이 씀
 */
export function stageTone(index, count) {
  const t = count > 1 ? index / (count - 1) : 0.5
  const color =
    t <= 0.5
      ? `color-mix(in srgb, var(--color-primary) ${Math.round(t * 200)}%, var(--color-primary-disabled))`
      : `color-mix(in srgb, var(--color-primary-ink) ${Math.round((t - 0.5) * 200)}%, var(--color-primary))`
  // 진한 쪽(3/4 넘음)만 흰 글자, 나머지는 검정 글자 (둘 다 대비 4.5:1 이상)
  const textColor = t > 0.75 ? 'var(--color-text-on-dark)' : 'var(--color-text-on-primary)'
  return { color, textColor }
}

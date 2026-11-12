// STT 결과 평가 (모델 비교용). backend/scripts/stt_compare.py와 같은 기준이다.
//  - CER: 정답 대본 대비 글자 오류율 (공백·문장부호 제외, 편집 거리 / 정답 글자 수)
//  - 미술 용어 정확도: 정답 대본에 나온 미술 용어 중 결과에도 나온 비율 (등장 횟수 기준)

export const ART_TERMS = [
  '구도', '소실점', '투시', '원근감', '명암', '명도', '채도', '색상', '보색', '대비',
  '반사광', '하이라이트', '그림자', '양감', '입체감', '공간감', '질감', '비례', '윤곽', '톤',
  '석고상', '정물', '기초디자인', '사고의 전환', '발상', '스케치', '묘사', '터치', '색감', '배경',
  '주제', '형태', '구성', '레이어', '농도', '번짐', '수채화', '소묘', '크로키', '여백',
]

const STRIP = /[\s.,!?·…'"‘’“”()[\]{}:;~-]/g

export const normalizeText = (text) => (text ?? '').replace(STRIP, '')

export function editDistance(a, b) {
  const x = [...a]
  const y = [...b]
  let prev = Array.from({ length: y.length + 1 }, (_, j) => j)
  for (let i = 1; i <= x.length; i += 1) {
    const cur = [i]
    for (let j = 1; j <= y.length; j += 1) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x[i - 1] === y[j - 1] ? 0 : 1))
    }
    prev = cur
  }
  return prev[y.length]
}

/** 글자 오류율 (0~1+). 정답이 비어 있으면 null */
export function cer(reference, hypothesis) {
  const ref = normalizeText(reference)
  if (!ref) return null
  return editDistance(ref, normalizeText(hypothesis)) / [...ref].length
}

function count(text, term) {
  const t = normalizeText(term)
  let n = 0
  for (let i = text.indexOf(t); i !== -1; i = text.indexOf(t, i + t.length)) n += 1
  return n
}

/** → { total, matched, ratio(0~1|null), missed: [용어] } */
export function termAccuracy(reference, hypothesis, terms = ART_TERMS) {
  const ref = normalizeText(reference)
  const hyp = normalizeText(hypothesis)
  let total = 0
  let matched = 0
  const missed = []
  for (const term of terms) {
    const want = count(ref, term)
    if (!want) continue
    const got = Math.min(want, count(hyp, term))
    total += want
    matched += got
    if (got < want) missed.push(term)
  }
  return { total, matched, ratio: total ? matched / total : null, missed }
}

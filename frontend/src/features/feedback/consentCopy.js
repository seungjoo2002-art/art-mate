// AI 전송 동의서 문구 (v0.9.6, 제공자별). 학생 동의 화면과 보호자 확인 화면이 같은 문구를 쓴다.
// 근거: OpenAI 데이터 처리(학습 미사용, 남용 감시 기록 최대 30일, 한국 내 처리 미지원),
// OpenAI 미성년자 가이드(만 18세 미만 보호자, 만 13세 미만 데이터 무보관 전 처리 금지),
// 개인정보 보호법 제22조의2(만 14세 미만 법정대리인 동의)·국외 이전 고지.
// 법률 검토 전 초안 — 확정 문구가 나오면 교체.

const RECIPIENT = {
  OPENAI: {
    name: 'OpenAI',
    who: 'OpenAI, L.L.C. (OpenAI API) · 미국 등 국외에서 처리돼요. 처리 국가를 한국으로 지정할 수 없어요.',
    keep: 'OpenAI: API로 보낸 내용은 모델 학습에 쓰이지 않고, 응답을 저장하지 않도록 요청해요. 오남용 감시 기록은 최대 30일 보관될 수 있어요.',
  },
  GOOGLE_GEMINI: {
    name: 'Google Gemini',
    who: 'Google LLC (Gemini API) · 미국 등 국외에서 처리돼요.',
    keep: 'Google: 유료 API 약관에 따라 처리되며 모델 학습에 쓰이지 않아요.',
  },
}

const AGE_ITEM = [
  '나이 확인',
  '생년월로 나이 구간만 확인하고 생년월은 저장하지 않아요. 만 18세 미만은 보호자(법정대리인)가 따로 확인해야 AI 정리를 쓸 수 있어요. 만 13세 미만은 아직 이용할 수 없어요.',
]

export function consentCopy(purpose, provider = 'OPENAI') {
  const r = RECIPIENT[provider] ?? RECIPIENT.OPENAI
  if (purpose === 'GROWTH_COACHING') {
    return {
      title: 'AI 성장 코칭 동의',
      sub: 'AI가 성장 리포트 설명과 연습 과제를 만들려면 아래 내용에 동의해 주세요.',
      items: [
        ['목적', '확정된 첨삭 기록을 바탕으로 성장 리포트 설명과 맞춤 연습 과제 초안을 만들어요.'],
        ['제공받는 곳', r.who],
        [
          '보내는 내용',
          '약점 카테고리별 통계(작품 수 등)와 확정된 첨삭 문장만 보내요. 작품 제목·이름·학원·계정 정보는 보내지 않아요.',
        ],
        ['보관', `ART MATE: 결과는 근거 첨삭을 삭제할 때까지 보관해요. ${r.keep}`],
        AGE_ITEM,
        ['거부할 권리', '동의하지 않아도 통계와 기본 연습 과제 추천은 그대로 쓸 수 있어요.'],
        [
          '동의 철회',
          '마이페이지에서 언제든 철회할 수 있어요. 진행 중인 AI 생성은 취소되고, 이미 만든 결과는 남아요(근거 첨삭이 삭제되면 설명도 삭제).',
        ],
      ],
      agree: `위 내용을 확인했고 확정된 첨삭 기록을 AI(${r.name})로 보내는 데 동의합니다.`,
      guardianAgree: `위 내용을 확인했고 자녀의 확정된 첨삭 기록을 AI(${r.name})로 보내는 데 동의합니다.`,
      submit: '동의하기',
    }
  }
  return {
    title: 'AI 피드백 정리 동의',
    sub: 'AI로 첨삭을 정리하려면 아래 내용에 동의해 주세요.',
    items: [
      ['목적', '첨삭 녹음을 글로 바꾼 내용(전사문)을 요약·분류해 학습 기록으로 정리해요.'],
      ['제공받는 곳', r.who],
      [
        '보내는 내용',
        '첨삭 녹음의 전사문(문장과 시각)만 보내요. 이름·학교·작품 제목·계정 정보는 보내지 않아요. 단, 녹음 안에서 말한 이름 등은 전사문에 포함될 수 있어요.',
      ],
      ['보관', `ART MATE: 전사문·요약은 녹음을 삭제할 때까지 보관해요. ${r.keep}`],
      AGE_ITEM,
      ['거부할 권리', '동의하지 않아도 녹음·재생·대본 보기는 그대로 쓸 수 있어요. AI 정리만 쓸 수 없어요.'],
      [
        '동의 철회',
        '마이페이지에서 언제든 철회할 수 있어요. 진행 중인 정리는 취소되고, 이미 만든 정리는 남아요.',
      ],
    ],
    agree: `위 내용을 확인했고 전사문을 AI(${r.name})로 보내는 데 동의합니다.`,
    guardianAgree: `위 내용을 확인했고 자녀의 전사문을 AI(${r.name})로 보내는 데 동의합니다.`,
    submit: '동의하고 AI로 정리하기',
  }
}

/** 동의가 아직 유효하지 않은 이유 → 학생에게 보여 줄 문장 (null이면 일반 동의 화면) */
export function consentReasonMessage(reason) {
  if (reason === 'GUARDIAN_PENDING') return '보호자 확인을 기다리고 있어요. 보호자가 링크에서 확인하면 AI 정리를 쓸 수 있어요.'
  if (reason === 'MINOR_BLOCKED')
    return '만 18세 미만은 아직 AI 첨삭 정리를 쓸 수 없어요. 준비가 끝나면 보호자 확인 후 쓸 수 있어요. 녹음과 대본은 그대로 쓸 수 있어요.'
  if (reason === 'UNDER_13_BLOCKED') return '만 13세 미만은 아직 AI 첨삭 정리를 쓸 수 없어요. 녹음과 대본은 그대로 쓸 수 있어요.'
  return null
}

/** 보호자 확인 링크 (토큰은 동의·재발급 응답에서 한 번만 받는다) */
export const guardianLink = (token, origin = globalThis.location?.origin ?? '') =>
  `${origin}/guardian-consent/${token}`

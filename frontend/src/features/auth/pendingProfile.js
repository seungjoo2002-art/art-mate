// 회원가입 폼 입력값(이름·유형)을 이메일 인증이 끝날 때까지 보관.
// 인증 메일 링크로 돌아오면 AuthProvider가 이 값으로 프로필을 만든다.
const KEY = 'artmate.pendingProfile'

export function savePendingProfile(profile) {
  try {
    localStorage.setItem(KEY, JSON.stringify(profile))
  } catch {
    // 저장 실패 시 로그인 후 온보딩 화면에서 다시 입력받음
  }
}

/** 같은 이메일로 가입한 경우에만 돌려줌 (다른 계정에 잘못 적용 방지) */
export function readPendingProfile(email) {
  try {
    const value = JSON.parse(localStorage.getItem(KEY))
    return value?.email === email ? value : null
  } catch {
    return null
  }
}

export function clearPendingProfile() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // 무시
  }
}

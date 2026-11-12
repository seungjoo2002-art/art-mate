// 로그인이 풀려 랜딩으로 보낼 때, 다시 로그인되면 원래 보던 화면으로 돌아가기 위한 경로 (탭 단위)
const KEY = 'artmate.returnPath'

export function rememberReturnPath(path) {
  if (!isSafePath(path)) return
  try {
    sessionStorage.setItem(KEY, path)
  } catch {
    // 저장소를 쓸 수 없으면 홈으로 이동
  }
}

/** 저장된 경로 (렌더 중 읽기용, 지우지 않음). 없거나 안전하지 않으면 null */
export function peekReturnPath() {
  try {
    const path = sessionStorage.getItem(KEY)
    return isSafePath(path) ? path : null
  } catch {
    return null
  }
}

export function clearReturnPath() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // 무시
  }
}

/** 앱 안의 보호 화면 경로만 허용 (외부 주소·로그인 화면 제외) */
export function isSafePath(path) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) return false
  return !['/', '/login', '/signup', '/onboarding'].includes(path.split(/[?#]/)[0])
}

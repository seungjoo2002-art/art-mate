import { api } from './api'

// 선택지(실기 유형, 약점 카테고리 등)는 서버 설정이라 앱 실행 중 한 번만 받아 둠
let cached = null

/** GET /meta/options (인증 불필요). 실패하면 다음 호출 때 다시 시도 */
export function getOptions() {
  if (!cached) {
    cached = api('/meta/options').catch((error) => {
      cached = null
      throw error
    })
  }
  return cached
}

/** [{ code, label }] → code로 label 찾기. 없으면 code 그대로 */
export function labelOf(list, code) {
  return list?.find((item) => item.code === code)?.label ?? code
}

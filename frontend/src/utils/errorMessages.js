// Supabase Auth 오류 (error.code)
const AUTH_MESSAGES = {
  invalid_credentials: '이메일 또는 비밀번호가 올바르지 않아요.',
  email_not_confirmed: '이메일 인증을 먼저 완료해 주세요. 받은 메일함을 확인해 보세요.',
  user_already_exists: '이미 가입된 이메일이에요. 로그인해 주세요.',
  email_exists: '이미 가입된 이메일이에요. 로그인해 주세요.',
  weak_password: '비밀번호가 너무 단순해요. 다른 비밀번호를 입력해 주세요.',
  email_address_invalid: '사용할 수 없는 이메일 주소예요.',
  over_email_send_rate_limit: '메일 발송 한도를 넘었어요. 잠시 후 다시 시도해 주세요.',
  over_request_rate_limit: '요청이 너무 많아요. 잠시 후 다시 시도해 주세요.',
}

// ART MATE API 오류 (docs/frontend-integration.md §8)
const API_MESSAGES = {
  NETWORK_ERROR: '서버에 연결할 수 없어요. 인터넷 연결이나 백엔드 서버 상태를 확인해 주세요.',
  ACCOUNT_DISABLED: '이용이 중지된 계정이에요. 운영자에게 문의해 주세요.',
  AUTH_NOT_CONFIGURED: '서버 인증 설정이 필요해요. 백엔드 담당자에게 문의해 주세요.',
  DATABASE_UNAVAILABLE: '서버가 잠시 불안정해요. 잠시 후 다시 시도해 주세요.',
  AUTH_PROVIDER_UNAVAILABLE: '서버가 잠시 불안정해요. 잠시 후 다시 시도해 주세요.',
  VALIDATION_ERROR: '입력한 내용을 다시 확인해 주세요.',
}

export function toErrorMessage(error) {
  return (
    AUTH_MESSAGES[error?.code] ??
    API_MESSAGES[error?.code] ??
    '문제가 발생했어요. 잠시 후 다시 시도해 주세요.'
  )
}

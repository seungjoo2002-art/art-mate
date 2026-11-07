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
  NOT_FOUND: '찾을 수 없거나 볼 수 없는 항목이에요.',
  FORBIDDEN: '이 기능을 사용할 권한이 없어요.',

  // 작품 사진 (docs/frontend-integration-v0.4.md §7)
  UNSUPPORTED_FILE_TYPE: 'JPG, PNG, WEBP 사진만 올릴 수 있어요.',
  FILE_TOO_LARGE: '10MB 이하 사진만 올릴 수 있어요.',
  INVALID_IMAGE: '사진 파일을 읽을 수 없어요. 다른 사진을 선택해 주세요.',
  PHOTO_LIMIT_REACHED: '이 단계에 올릴 수 있는 사진 수를 넘었어요.',
  DUPLICATE_PHOTO: '이미 올린 사진이에요.',
  UPLOAD_EXPIRED: '업로드 시간이 지났어요. 다시 올려 주세요.',
  UPLOAD_NOT_FOUND: '업로드가 끝나지 않았어요. 다시 올려 주세요.',
  STORAGE_UNAVAILABLE: '사진 저장소가 잠시 불안정해요. 잠시 후 다시 시도해 주세요.',
  STORAGE_NOT_CONFIGURED: '서버 사진 저장소 설정이 필요해요. 백엔드 담당자에게 문의해 주세요.',
}

export function toErrorMessage(error) {
  if (error?.userMessage) return error.userMessage // 프론트에서 직접 만든 안내
  return (
    AUTH_MESSAGES[error?.code] ??
    API_MESSAGES[error?.code] ??
    '문제가 발생했어요. 잠시 후 다시 시도해 주세요.'
  )
}

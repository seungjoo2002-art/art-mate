import { Button } from '../components/ui'
import FullScreenStatus from '../components/layout/FullScreenStatus'
import { toErrorMessage } from '../utils/errorMessages'
import { useAuth } from './providers/AuthContext'

/** status가 loading / error / misconfigured일 때 공통으로 보여 주는 화면 */
export default function AuthStatusScreen() {
  const { status, error, retry, signOut } = useAuth()

  if (status === 'misconfigured') {
    return (
      <FullScreenStatus
        title="환경 설정이 필요해요"
        description={'frontend/.env.example을 복사해 .env.local을 만들고\nSupabase 값을 채운 뒤 개발 서버를 다시 실행해 주세요.'}
      />
    )
  }

  if (status === 'error') {
    return (
      <FullScreenStatus title="정보를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={retry}>다시 시도</Button>
        <Button variant="soft" onClick={signOut}>
          로그아웃
        </Button>
      </FullScreenStatus>
    )
  }

  return <FullScreenStatus />
}

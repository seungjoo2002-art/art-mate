import { useLocation, useNavigate } from 'react-router-dom'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import { Button } from '../../../components/ui'

export default function CheckEmailPage() {
  const navigate = useNavigate()
  const email = useLocation().state?.email

  return (
    <FullScreenStatus
      title="메일함을 확인해 주세요"
      description={`${email ?? '입력한 이메일'}로 인증 메일을 보냈어요.\n메일의 링크를 누르면 가입이 완료돼요.`}
    >
      <Button variant="soft" onClick={() => navigate('/login')}>
        로그인 화면으로
      </Button>
    </FullScreenStatus>
  )
}

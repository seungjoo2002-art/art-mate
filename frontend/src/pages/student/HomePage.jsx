import { useAuth } from '../../app/providers/AuthContext'
import { PageIntro } from '../../components/ui'
import { formatToday } from '../../utils/date'

export default function HomePage() {
  const { profile } = useAuth()

  return (
    <PageIntro
      eyebrow={formatToday()}
      title={`안녕하세요, ${profile.display_name}님!`}
      description="오늘도 한 단계 성장해 볼까요?"
    />
  )
}

import { useAuth } from '../../app/providers/AuthContext'
import { PageIntro } from '../../components/ui'
import { formatToday } from '../../utils/date'

// TODO: 강사 메인 디자인 나오면 구성 (현재 디자인 없음)
export default function HomePage() {
  const { profile } = useAuth()

  return (
    <PageIntro
      eyebrow={formatToday()}
      title={`안녕하세요, ${profile.display_name} 선생님!`}
      description="오늘 학생들의 성장을 함께 살펴볼까요?"
    />
  )
}

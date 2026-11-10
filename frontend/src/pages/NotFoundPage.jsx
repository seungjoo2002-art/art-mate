import { useNavigate } from 'react-router-dom'
import { Button, PageIntro } from '../components/ui'

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <main style={{ display: 'grid', gap: 'var(--space-8)', padding: 'var(--space-10) var(--gutter)' }}>
      <PageIntro eyebrow="404" title="페이지를 찾을 수 없어요" />
      <Button onClick={() => navigate('/home')}>홈으로</Button>
    </main>
  )
}

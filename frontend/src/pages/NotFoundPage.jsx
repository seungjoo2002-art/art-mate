import { useNavigate } from 'react-router-dom'
import MascotCheer from '../components/mascot/MascotCheer'
import { Button } from '../components/ui'

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <main style={{ display: 'grid', gap: 'var(--space-8)', padding: 'var(--space-10) var(--gutter)' }}>
      <MascotCheer as="h1" pose="curious" eyebrow="404" sub="주소가 바뀌었거나 없어진 페이지예요.">
        페이지를 찾을 수 없어요
      </MascotCheer>
      <Button size="compact" onClick={() => navigate('/home')}>
        홈으로
      </Button>
    </main>
  )
}

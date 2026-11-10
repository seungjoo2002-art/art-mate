import { useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Card, PageIntro } from '../../components/ui'
import GrowthOverview from '../../features/growth/components/GrowthOverview'
import RecentFeedbacks from '../../features/growth/components/RecentFeedbacks'
import { listArtworks } from '../../features/artworks/api'
import ArtworkCard from '../../features/artworks/components/ArtworkCard'
import { isCompleted } from '../../features/artworks/stages'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './ArchivePage.module.css'

const TABS = [
  { key: 'artworks', label: '전체 작품' },
  { key: 'feedbacks', label: '첨삭' },
  { key: 'growth', label: '성장 분석' },
]

export default function ArchivePage() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((t) => t.key === params.get('tab')) ? params.get('tab') : 'artworks'

  return (
    <>
      <PageIntro
        eyebrow="GROWTH ARCHIVE"
        title="나의 성장 기록"
        description="완성보다 과정에 집중해온 기록이에요."
      />
      <div className={styles.tabs} role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`${styles.tab} ${tab === t.key ? styles.tabActive : ''}`}
            onClick={() => setParams(t.key === 'artworks' ? {} : { tab: t.key }, { replace: true })}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'artworks' && <ArtworkArchive />}
      {tab === 'feedbacks' && <RecentFeedbacks />}
      {tab === 'growth' && <GrowthOverview />}
    </>
  )
}

function ArtworkArchive() {
  const navigate = useNavigate()
  const load = useCallback(() => listArtworks(), [])
  const { data, error, reload } = useAsync(load)

  if (error) {
    return (
      <Card variant="soft" className={styles.message}>
        {toErrorMessage(error)}
        <Button variant="soft" size="md" onClick={reload}>
          다시 시도
        </Button>
      </Card>
    )
  }
  if (!data) return null

  const artworks = data.items
  const latest = artworks[0]?.work_date // 작업 날짜 최신순

  return (
    <>
      <Card variant="dark" className={styles.stats}>
        <Stat value={data.total} label="총 작품" />
        <Stat value={artworks.filter(isCompleted).length} label="완성 작품" />
        <Stat value={latest ? latest.slice(5).replace('-', '.') : '-'} label="최근 작업" />
      </Card>

      {artworks.length === 0 ? (
        <Card className={styles.message}>
          아직 기록한 작품이 없어요.
          <Button size="md" onClick={() => navigate('/artworks/new')}>
            첫 작품 기록하기
          </Button>
        </Card>
      ) : (
        <div className={styles.grid}>
          {artworks.map((artwork) => (
            <ArtworkCard key={artwork.id} artwork={artwork} />
          ))}
        </div>
      )}
    </>
  )
}

function Stat({ value, label }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}

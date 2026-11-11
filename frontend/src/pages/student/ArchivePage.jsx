import { useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Card, Chip, PageIntro, SegmentedTabs } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import ArtworkCard from '../../features/artworks/components/ArtworkCard'
import MyPostsFeed from '../../features/community/components/MyPostsFeed'
import GrowthOverview from '../../features/growth/components/GrowthOverview'
import RecentFeedbacks from '../../features/growth/components/RecentFeedbacks'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './ArchivePage.module.css'

const TABS = [
  { key: 'artworks', label: '전체 기록' },
  { key: 'feed', label: '공개 피드' },
  { key: 'report', label: '분석 리포트' },
]

// 선택한 탭·실기 유형은 주소(?tab=&type=)에 남겨서 뒤로가기·새로고침해도 유지
export default function ArchivePage() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((t) => t.key === params.get('tab')) ? params.get('tab') : 'artworks'

  return (
    <>
      <PageIntro
        title="아카이브"
        description="나의 작품·공개 피드·학습 분석을 한 곳에서 확인하세요."
      />
      <SegmentedTabs
        label="아카이브"
        tabs={TABS}
        value={tab}
        onChange={(key) => setParams(key === 'artworks' ? {} : { tab: key }, { replace: true })}
      />
      {tab === 'artworks' && (
        <ArtworkArchive
          practicalType={params.get('type') ?? ''}
          onTypeChange={(type) => setParams(type ? { type } : {}, { replace: true })}
        />
      )}
      {tab === 'feed' && <MyPostsFeed />}
      {tab === 'report' && (
        <>
          <GrowthOverview />
          <section className={styles.section}>
            <h2 className={styles.heading}>최근 확정한 첨삭</h2>
            <RecentFeedbacks />
          </section>
        </>
      )}
    </>
  )
}

/** 내 작품: 실기 유형 칩으로 거르기 (디자인의 "실기 유형 관리"는 백엔드가 없어 제외) */
function ArtworkArchive({ practicalType, onTypeChange }) {
  const navigate = useNavigate()
  const options = useOptions()
  const load = useCallback(() => listArtworks({ practicalType }), [practicalType])
  const { data, error, reload } = useAsync(load)
  const types = [{ code: '', label: '전체' }, ...(options?.practical_types ?? [])]

  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>내 작품</h2>
      <div className={styles.chips}>
        {types.map((t) => (
          <Chip
            key={t.code || 'all'}
            selected={practicalType === t.code}
            onClick={() => onTypeChange(t.code)}
          >
            {t.label}
          </Chip>
        ))}
      </div>

      {error ? (
        <Card variant="soft" className={styles.message}>
          {toErrorMessage(error)}
          <Button variant="soft" size="md" onClick={reload}>
            다시 시도
          </Button>
        </Card>
      ) : !data ? null : data.items.length === 0 ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>
            {practicalType
              ? '이 실기 유형으로 기록한 작품이 없습니다.'
              : '아직 등록된 작품이 없습니다.'}
          </p>
          <p className={styles.emptySub}>실기 메뉴에서 작품을 기록하면 이곳에 자동 정리됩니다.</p>
          <Button size="md" fullWidth={false} onClick={() => navigate('/artworks/new')}>
            새 작품 기록
          </Button>
        </div>
      ) : (
        <div className={styles.grid}>
          {data.items.map((artwork) => (
            <ArtworkCard key={artwork.id} artwork={artwork} />
          ))}
        </div>
      )}
    </section>
  )
}

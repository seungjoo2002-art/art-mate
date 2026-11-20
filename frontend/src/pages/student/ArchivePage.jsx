import { useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import MascotCheer from '../../components/mascot/MascotCheer'
import { Button, Card, PageIntro, SegmentedTabs } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import PaintChips from '../../features/artworks/components/PaintChips'
import SketchPageCard from '../../features/artworks/components/SketchPageCard'
import MyPostsFeed from '../../features/community/components/MyPostsFeed'
import AnalysisReport from '../../features/growth/components/AnalysisReport'
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
      <PageIntro title="아카이브" />
      <SegmentedTabs
        variant="highlight"
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
      {tab === 'report' && <AnalysisReport />}
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
      <h2 className={styles.srOnly}>내 작품</h2>
      <PaintChips
        label="실기 유형"
        options={types}
        value={practicalType}
        onChange={onTypeChange}
        wrap={false}
      />

      {error ? (
        <Card variant="soft" className={styles.message}>
          {toErrorMessage(error)}
          <Button variant="soft" size="md" onClick={reload}>
            다시 시도
          </Button>
        </Card>
      ) : !data ? null : data.items.length === 0 ? (
        <div className={styles.empty}>
          <MascotCheer
            pose="curious"
            sub="실기 메뉴에서 작품을 기록하면 이곳에 자동 정리돼요."
          >
            {practicalType ? '이 실기 유형으로 기록한 작품이 없어요' : '아직 기록한 작품이 없어요'}
          </MascotCheer>
          <Button size="compact" onClick={() => navigate('/artworks/new')}>
            새 작품 기록
          </Button>
        </div>
      ) : (
        <div className={styles.grid}>
          {data.items.map((artwork) => (
            <SketchPageCard key={artwork.id} artwork={artwork} />
          ))}
        </div>
      )}
    </section>
  )
}

import { useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import MascotCheer from '../../components/mascot/MascotCheer'
import { Button, Card, PageIntro, SegmentedTabs } from '../../components/ui'
import { listArtworks } from '../../features/artworks/api'
import {
  ARCHIVE_EMPTY,
  ARCHIVE_KINDS,
  archiveItems,
  archiveKind,
  archiveQuery,
} from '../../features/artworks/archiveView'
import ArtworkCard from '../../features/artworks/components/ArtworkCard'
import PaintChips from '../../features/artworks/components/PaintChips'
import MyPostsFeed from '../../features/community/components/MyPostsFeed'
import AnalysisReport from '../../features/growth/components/AnalysisReport'
import { useAsync } from '../../hooks/useAsync'
import { useOptions } from '../../hooks/useOptions'
import { labelOf } from '../../lib/options'
import { toErrorMessage } from '../../utils/errorMessages'
import styles from './ArchivePage.module.css'

const TABS = [
  { key: 'artworks', label: '전체 기록' },
  { key: 'feed', label: '공개 피드' },
  { key: 'report', label: '분석 리포트' },
]

// 선택한 탭·작품 분류는 주소(?tab=&kind=)에 남겨서 뒤로가기·새로고침해도 유지
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
          kind={archiveKind(params.get('kind'))}
          onKindChange={(kind) => setParams(kind ? { kind } : {}, { replace: true })}
        />
      )}
      {tab === 'feed' && <MyPostsFeed />}
      {tab === 'report' && <AnalysisReport />}
    </>
  )
}

/**
 * 내 작품: 실기시험 · 실기 모의고사 · 내 작품 기록으로 거르기 (서버의 work_category 기준).
 * 실기 유형(기초디자인 등)은 분류가 아니라 카드의 작은 태그로 보여 준다.
 */
function ArtworkArchive({ kind, onKindChange }) {
  const navigate = useNavigate()
  const options = useOptions()
  const load = useCallback(() => {
    const query = archiveQuery(kind)
    return query ? listArtworks(query) : Promise.resolve({ items: [] })
  }, [kind])
  const { data, error, reload } = useAsync(load)
  const items = data ? archiveItems(kind, data.items) : []
  const [emptyTitle, emptyText] = ARCHIVE_EMPTY[kind]
  const typeLabel = (code) => (code && options ? labelOf(options.practical_types, code) : null)

  return (
    <section className={styles.section}>
      <h2 className={styles.srOnly}>내 작품</h2>
      <PaintChips
        label="작품 분류"
        options={ARCHIVE_KINDS}
        value={kind}
        onChange={onKindChange}
        wrap={false}
        colorOf={() => null}
      />

      {error ? (
        <Card variant="soft" className={styles.message}>
          작품을 불러오지 못했어요. {toErrorMessage(error)}
          <Button variant="soft" size="md" onClick={reload}>
            다시 시도
          </Button>
        </Card>
      ) : !data ? null : items.length === 0 ? (
        <div className={styles.empty}>
          <MascotCheer pose="curious" sub={emptyText}>
            {emptyTitle}
          </MascotCheer>
          {kind !== 'mock' && (
            <Button
              size="compact"
              onClick={() => navigate(kind === 'exam' ? '/artworks/new?mode=exam' : '/artworks/new')}
            >
              {kind === 'exam' ? '실기시험 시작하기' : '새 작품 기록'}
            </Button>
          )}
        </div>
      ) : (
        <div className={styles.grid}>
          {items.map((artwork) => (
            <ArtworkCard
              key={artwork.id}
              artwork={artwork}
              typeLabel={typeLabel(artwork.practical_type)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

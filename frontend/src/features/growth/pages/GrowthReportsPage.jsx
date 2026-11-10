import { useCallback, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import TopBar from '../../../components/layout/TopBar'
import { Button, Card, Checkbox, Chip, PageIntro } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { createReport, listReports } from '../api'
import { PERIOD_LABELS } from '../labels'
import styles from './GrowthPage.module.css'

const PERIODS = ['WEEK', 'MONTH', 'ALL']

/** 성장 리포트 만들기 + 지난 리포트 목록 */
export default function GrowthReportsPage() {
  const navigate = useNavigate()
  const load = useCallback(() => listReports(), [])
  const { data } = useAsync(load)
  const [period, setPeriod] = useState('MONTH')
  const [includeAi, setIncludeAi] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  async function handleCreate() {
    setCreating(true)
    setError('')
    try {
      const report = await createReport({ period, includeAi })
      navigate(`/growth/reports/${report.id}`)
    } catch (err) {
      setError(toErrorMessage(err))
      setCreating(false)
    }
  }

  return (
    <>
      <TopBar title="성장 리포트" belowHeader />
      <main className={styles.body}>
        <PageIntro
          eyebrow="GROWTH REPORT"
          title="기간별 성장 리포트"
          description="확정된 첨삭 기록으로 자주 지적된 부분과 학습 시간을 정리해요."
        />

        <Card className={styles.section}>
          <span className={styles.label}>분석 기간</span>
          <div className={styles.chips}>
            {PERIODS.map((p) => (
              <Chip key={p} selected={period === p} onClick={() => setPeriod(p)}>
                {PERIOD_LABELS[p]}
              </Chip>
            ))}
          </div>
          <Checkbox checked={includeAi} onChange={setIncludeAi}>
            AI 설명도 함께 받기 (AI 성장 코칭 동의 필요)
          </Checkbox>
          {error && <p className={styles.error}>{error}</p>}
          <Button onClick={handleCreate} disabled={creating}>
            {creating ? '만드는 중…' : '리포트 만들기'}
          </Button>
        </Card>

        {data?.items.length > 0 && (
          <section className={styles.section}>
            <h2 className={styles.heading}>지난 리포트</h2>
            <ul className={styles.list}>
              {data.items.map((report) => (
                <li key={report.id}>
                  <Card as={Link} to={`/growth/reports/${report.id}`} className={styles.row}>
                    <span className={styles.rowText}>
                      <span className={styles.rowTitle}>{PERIOD_LABELS[report.period_type]}</span>
                      <span className={styles.caption}>
                        {report.period_start
                          ? `${report.period_start} ~ ${report.period_end}`
                          : '전체 기간'}
                        {report.status === 'INSUFFICIENT_DATA' && ' · 기록 부족'}
                      </span>
                    </span>
                    <ChevronRight size={20} aria-hidden />
                  </Card>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
    </>
  )
}

import { useCallback } from 'react'
import { ChevronRight, FileText, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, IconBox } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import { getWeaknesses } from '../api'
import WeaknessAnalysis from './WeaknessAnalysis'
import styles from './GrowthOverview.module.css'

/** 아카이브 "성장 분석" 탭: 리포트·연습 과제 바로가기 + 반복 약점 분석 */
export default function GrowthOverview() {
  const load = useCallback(() => getWeaknesses(), [])
  const { data, error } = useAsync(load)

  return (
    <div className={styles.wrap}>
      <div className={styles.links}>
        <Card as={Link} to="/growth/reports" className={styles.link}>
          <IconBox icon={FileText} />
          <span className={styles.linkText}>성장 리포트</span>
          <ChevronRight size={18} aria-hidden />
        </Card>
        <Card as={Link} to="/growth/recommendations" className={styles.link}>
          <IconBox icon={Target} />
          <span className={styles.linkText}>맞춤 연습 과제</span>
          <ChevronRight size={18} aria-hidden />
        </Card>
      </div>
      {error && <Card variant="soft">{toErrorMessage(error)}</Card>}
      {data && <WeaknessAnalysis analysis={data} />}
    </div>
  )
}

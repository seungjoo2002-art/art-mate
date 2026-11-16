import { useCallback } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { listStaffArtworks } from '../../academy/api'
import { groupByStudent } from '../../academy/academyState'
import styles from '../Instructor.module.css'

const PROGRESS = { NOT_STARTED: '시작 전', SKETCH: '스케치', PROGRESS: '진행 중', FINAL: '완성' }

/** 담당 반 학생 작품 (학원에 연결된 작품만, 학생별로 묶어서) */
export default function StaffArtworksPage() {
  const { academy } = useOutletContext()
  const base = `/instructor/academies/${academy.id}`
  const load = useCallback(() => listStaffArtworks(academy.id, { limit: 100 }), [academy.id])
  const { data, error } = useAsync(load)

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <h1 className={styles.title}>학생 작품</h1>
          <p className={styles.subtitle}>
            담당 반 학생이 이 학원으로 기록한 작품이에요. 개인 작품은 보이지 않아요.
          </p>
        </div>
      </div>
      {error ? (
        <p className={styles.error}>{toErrorMessage(error)}</p>
      ) : !data ? (
        <p className={styles.hint}>불러오는 중…</p>
      ) : data.items.length === 0 ? (
        <p className={styles.empty}>
          아직 학원에 연결된 작품이 없어요. 학생이 작품을 만들 때 이 학원·반을 선택하면 여기에 보여요.
        </p>
      ) : (
        groupByStudent(data.items).map((group) => (
          <section key={group.student?.membership_id} className={styles.section}>
            <div className={styles.sectionHead}>
              <h2 className={styles.sectionTitle}>
                {group.student?.display_name} <span className={styles.hint}>{group.artworks.length}작품</span>
              </h2>
              <Link
                to={`${base}/feedbacks?student=${group.student?.membership_id}`}
                className={styles.link}
              >
                첨삭 보기
              </Link>
            </div>
            <ul className={styles.list}>
              {group.artworks.map((a) => (
                <li key={a.id} className={styles.row}>
                  <Link to={`${base}/artworks/${a.id}`} className={styles.rowLink}>
                    <span className={styles.rowMain}>
                      <span className={styles.rowTitle}>{a.title}</span>
                      <span className={styles.rowSub}>
                        {formatMonthDay(a.work_date)} · {PROGRESS[a.progress] ?? a.progress} · 사진{' '}
                        {a.photo_count} · 녹음 {a.recording_count}
                      </span>
                    </span>
                    <span className={a.work_status === 'COMPLETED' ? styles.statusDone : styles.status}>
                      {a.work_status === 'COMPLETED' ? '완성' : '작업 중'}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
      {data && data.total > data.items.length && (
        <p className={styles.hint}>
          전체 {data.total}작품 중 최근 {data.items.length}작품을 보여 주고 있어요.
        </p>
      )}
    </>
  )
}

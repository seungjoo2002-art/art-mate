import { useCallback } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import { ACADEMY_ROLE_LABELS, isAcademyAdmin } from '../../../app/roles'
import { Button } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { formatMonthDay } from '../../../utils/date'
import { toErrorMessage } from '../../../utils/errorMessages'
import { listClasses, listJoinRequests, listReviewQueue, listStaffArtworks } from '../../academy/api'
import { dashboardStats } from '../../academy/academyState'
import { FEEDBACK_STATUS, formatDateTime } from '../status'
import StatusBadge from '../StatusBadge'
import styles from '../Instructor.module.css'

/** 강사 대시보드: 담당 반·학생, 작품 제출, 첨삭 검토 대기, 최근 승인 */
export default function AcademyDashboardPage() {
  const { academy } = useOutletContext()
  const admin = isAcademyAdmin(academy.my_role)
  const base = `/instructor/academies/${academy.id}`

  const load = useCallback(
    () =>
      Promise.all([
        // 원장·관리자는 학원 전체 반, 강사는 담당 반
        listClasses(academy.id, { mine: !admin }),
        listStaffArtworks(academy.id, { limit: 8 }),
        listReviewQueue(academy.id, { limit: 8 }),
        listReviewQueue(academy.id, { status: 'APPROVED', limit: 5 }),
        admin ? listJoinRequests(academy.id) : Promise.resolve(null),
      ]).then(([classes, artworks, queue, approved, requests]) => ({
        classes: classes.items,
        artworks,
        queue,
        approved,
        requests,
      })),
    [academy.id, admin],
  )
  const { data, error, reload } = useAsync(load)

  if (error) {
    return (
      <div className={styles.empty}>
        <p>{toErrorMessage(error)}</p>
        <Button size="md" fullWidth={false} onClick={reload}>
          다시 시도
        </Button>
      </div>
    )
  }
  if (!data) return <p className={styles.hint}>불러오는 중…</p>

  const stats = dashboardStats(data)
  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <p className={styles.eyebrow}>{ACADEMY_ROLE_LABELS[academy.my_role]}</p>
          <h1 className={styles.title}>{academy.name}</h1>
          <p className={styles.subtitle}>{admin ? '학원 전체' : '내 담당 반'} 기준이에요.</p>
        </div>
      </div>

      <div className={styles.stats}>
        <Stat label="검토 대기 첨삭" value={stats.waiting} accent={stats.waiting > 0} to={`${base}/feedbacks`} />
        <Stat label="제출 작품" value={stats.artworks} to={`${base}/artworks`} />
        <Stat label={admin ? '반' : '담당 반'} value={stats.classes} to={`${base}/manage`} />
        <Stat label="배정 학생" value={stats.students} />
        <Stat label="승인한 첨삭" value={stats.approved} />
      </div>

      {admin && data.requests?.total > 0 && (
        <Link to={`${base}/manage?tab=requests`} className={`${styles.stat} ${styles.statAccent}`}>
          <span className={styles.statLabel}>새 소속 신청</span>
          <span className={styles.sectionTitle}>{data.requests.total}건 확인하기 &gt;</span>
        </Link>
      )}

      <div className={styles.twoCol}>
        <div className={styles.section}>
          <section className={styles.section}>
            <div className={styles.sectionHead}>
              <h2 className={styles.sectionTitle}>첨삭 검토 대기</h2>
              <Link to={`${base}/feedbacks`} className={styles.link}>
                전체 보기
              </Link>
            </div>
            {data.queue.items.length === 0 ? (
              <p className={styles.empty}>검토할 AI 첨삭 정리가 없어요.</p>
            ) : (
              <ul className={styles.list}>
                {data.queue.items.map((f) => (
                  <li key={f.id} className={styles.row}>
                    <Link to={`${base}/feedbacks/${f.id}`} className={styles.rowLink}>
                      <span className={styles.rowMain}>
                        <span className={styles.rowTitle}>
                          {f.student.display_name} · {f.artwork_title}
                        </span>
                        <span className={styles.rowSub}>
                          {f.recording_id ? '녹음 첨삭' : '글 첨삭'} · {formatDateTime(f.created_at)}
                        </span>
                      </span>
                      <StatusBadge status={FEEDBACK_STATUS[f.status]} fallback={f.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHead}>
              <h2 className={styles.sectionTitle}>최근 제출 작품</h2>
              <Link to={`${base}/artworks`} className={styles.link}>
                전체 보기
              </Link>
            </div>
            {data.artworks.items.length === 0 ? (
              <p className={styles.empty}>
                아직 학원에 연결된 작품이 없어요. 학생이 작품을 만들 때 이 학원과 반을 선택하면 보여요.
              </p>
            ) : (
              <ul className={styles.list}>
                {data.artworks.items.map((a) => (
                  <li key={a.id} className={styles.row}>
                    <Link to={`${base}/artworks/${a.id}`} className={styles.rowLink}>
                      <span className={styles.rowMain}>
                        <span className={styles.rowTitle}>
                          {a.student.display_name} · {a.title}
                        </span>
                        <span className={styles.rowSub}>
                          {formatMonthDay(a.work_date)} · 사진 {a.photo_count} · 녹음 {a.recording_count}
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div className={styles.section}>
          <section className={styles.section}>
            <div className={styles.sectionHead}>
              <h2 className={styles.sectionTitle}>{admin ? '반' : '담당 반'}</h2>
              <Link to={`${base}/manage`} className={styles.link}>
                {admin ? '관리' : '보기'}
              </Link>
            </div>
            {data.classes.length === 0 ? (
              <p className={styles.empty}>
                {admin ? '반을 만들고 학생·강사를 배정해 주세요.' : '아직 담당 반이 없어요. 원장·관리자에게 배정을 요청해 주세요.'}
              </p>
            ) : (
              <ul className={styles.list}>
                {data.classes.map((c) => (
                  <li key={c.id} className={styles.row}>
                    <Link to={`${base}/classes/${c.id}`} className={styles.rowLink}>
                      <span className={styles.rowMain}>
                        <span className={styles.rowTitle}>{c.name}</span>
                        <span className={styles.rowSub}>
                          학생 {c.student_count}명
                          {c.instructors?.length
                            ? ` · 담당 ${c.instructors.map((i) => i.display_name).join(', ')}`
                            : ' · 담당 강사 없음'}
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>최근 승인한 첨삭</h2>
            {data.approved.items.length === 0 ? (
              <p className={styles.empty}>아직 승인한 첨삭이 없어요.</p>
            ) : (
              <ul className={styles.list}>
                {data.approved.items.map((f) => (
                  <li key={f.id} className={styles.row}>
                    <Link to={`${base}/feedbacks/${f.id}`} className={styles.rowLink}>
                      <span className={styles.rowMain}>
                        <span className={styles.rowTitle}>
                          {f.student.display_name} · {f.artwork_title}
                        </span>
                        <span className={styles.rowSub}>{formatDateTime(f.updated_at)}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  )
}

function Stat({ label, value, to, accent = false }) {
  const content = (
    <>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </>
  )
  const className = `${styles.stat} ${accent ? styles.statAccent : ''}`
  return to ? (
    <Link to={to} className={className}>
      {content}
    </Link>
  ) : (
    <div className={className}>{content}</div>
  )
}

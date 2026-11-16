import { useCallback, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import { ACADEMY_ROLE_LABELS, isAcademyAdmin } from '../../../app/roles'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  addClassMember,
  getClass,
  listClassMembers,
  listMembers,
  removeClassMember,
} from '../../academy/api'
import { unassignedMembers } from '../../academy/academyState'
import styles from '../Instructor.module.css'

/** 반 배정: 학생 배정(강사 이상) · 담당 강사 지정(원장·관리자) */
export default function ClassPage() {
  const { academy } = useOutletContext()
  const { classId } = useParams()
  const admin = isAcademyAdmin(academy.my_role)
  const base = `/instructor/academies/${academy.id}`

  const load = useCallback(
    () =>
      Promise.all([
        getClass(academy.id, classId),
        listClassMembers(academy.id, classId),
        listMembers(academy.id),
      ]).then(([klass, classMembers, members]) => ({
        klass,
        classMembers: classMembers.items,
        members: members.items,
      })),
    [academy.id, classId],
  )
  const { data, error, reload } = useAsync(load)
  const [busy, setBusy] = useState(null)
  const [actionError, setActionError] = useState('')

  async function run(key, action) {
    setBusy(key)
    setActionError('')
    try {
      await action()
      reload()
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  if (error) {
    return (
      <div className={styles.empty}>
        <p>{toErrorMessage(error)}</p>
        <Link to={`${base}/manage`} className={styles.link}>
          학원 관리로
        </Link>
      </div>
    )
  }
  if (!data) return <p className={styles.hint}>불러오는 중…</p>

  const active = data.classMembers.filter((m) => m.status === 'ACTIVE')
  const groups = [
    { role: 'INSTRUCTOR', title: '담당 강사', members: active.filter((m) => m.role === 'INSTRUCTOR') },
    { role: 'STUDENT', title: '학생', members: active.filter((m) => m.role === 'STUDENT') },
  ]

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <Link to={`${base}/manage`} className={styles.link}>
            &lt; 학원 관리
          </Link>
          <h1 className={styles.title}>{data.klass.name}</h1>
          <p className={styles.subtitle}>
            {data.klass.subject ? `${data.klass.subject} · ` : ''}학생 {data.klass.student_count}명
          </p>
        </div>
      </div>
      {actionError && <p className={styles.error}>{actionError}</p>}

      <div className={styles.grid}>
        {groups.map((group) => {
          const candidates = unassignedMembers(data.members, data.classMembers, group.role)
          const canAssign = group.role === 'STUDENT' || admin
          return (
            <section key={group.role} className={styles.section}>
              <h2 className={styles.sectionTitle}>
                {group.title} <span className={styles.hint}>{group.members.length}명</span>
              </h2>
              {group.members.length === 0 ? (
                <p className={styles.empty}>아직 배정되지 않았어요.</p>
              ) : (
                <ul className={styles.list}>
                  {group.members.map((m) => (
                    <li key={m.id} className={styles.row}>
                      <span className={styles.rowMain}>
                        <span className={styles.rowTitle}>{m.display_name}</span>
                      </span>
                      {canAssign && (
                        <button
                          type="button"
                          className={styles.smallButton}
                          disabled={busy !== null}
                          onClick={() => run(m.id, () => removeClassMember(academy.id, classId, m.id))}
                        >
                          배정 해제
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {canAssign && candidates.length > 0 && (
                <>
                  <h3 className={styles.rowSub}>배정할 수 있는 {group.title}</h3>
                  <ul className={styles.list}>
                    {candidates.map((m) => (
                      <li key={m.id} className={styles.row}>
                        <span className={styles.rowMain}>
                          <span className={styles.rowTitle}>{m.display_name}</span>
                          <span className={styles.rowSub}>{ACADEMY_ROLE_LABELS[m.role]}</span>
                        </span>
                        <button
                          type="button"
                          className={styles.smallPrimary}
                          disabled={busy !== null}
                          onClick={() => run(m.id, () => addClassMember(academy.id, classId, m.id))}
                        >
                          배정
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          )
        })}
      </div>
    </>
  )
}

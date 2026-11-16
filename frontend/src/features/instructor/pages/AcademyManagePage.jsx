import { useCallback, useState } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../../app/providers/AuthContext'
import { ACADEMY_ROLE_LABELS, isAcademyAdmin } from '../../../app/roles'
import { Card, Input, SegmentedTabs } from '../../../components/ui'
import { useAsync } from '../../../hooks/useAsync'
import { toErrorMessage } from '../../../utils/errorMessages'
import {
  createClass,
  listClasses,
  listJoinRequests,
  listMembers,
  removeMember,
  reviewJoinRequest,
  setMemberRole,
} from '../../academy/api'
import { formatDateTime } from '../status'
import styles from '../Instructor.module.css'

/** 학원 관리: 반 · 멤버 · 소속 신청 (원장·관리자만 변경, 강사는 보기) */
export default function AcademyManagePage() {
  const { academy } = useOutletContext()
  const admin = isAcademyAdmin(academy.my_role)
  const [params, setParams] = useSearchParams()
  const tabs = [
    { key: 'classes', label: '반' },
    { key: 'members', label: '멤버' },
    ...(admin ? [{ key: 'requests', label: '소속 신청' }] : []),
  ]
  const tab = tabs.some((t) => t.key === params.get('tab')) ? params.get('tab') : 'classes'

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <h1 className={styles.title}>학원 관리</h1>
          <p className={styles.subtitle}>
            {admin
              ? '반을 만들고, 소속 신청을 승인한 뒤 반에 학생과 담당 강사를 배정해 주세요.'
              : '반과 멤버를 볼 수 있어요. 변경은 원장·관리자가 해요.'}
          </p>
        </div>
      </div>
      <SegmentedTabs label="관리 항목" tabs={tabs} value={tab} onChange={(key) => setParams({ tab: key })} />
      {tab === 'classes' && <ClassesTab academy={academy} admin={admin} />}
      {tab === 'members' && <MembersTab academy={academy} admin={admin} />}
      {tab === 'requests' && admin && <RequestsTab academy={academy} />}
    </>
  )
}

function useAction(after) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')
  const run = async (key, action) => {
    setBusy(key)
    setError('')
    try {
      await action()
      after?.()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }
  return { busy, error, run }
}

function ClassesTab({ academy, admin }) {
  const base = `/instructor/academies/${academy.id}`
  const load = useCallback(() => listClasses(academy.id, { mine: !admin }), [academy.id, admin])
  const { data, error, reload } = useAsync(load)
  const [name, setName] = useState('')
  const [subject, setSubject] = useState('')
  const action = useAction(() => {
    setName('')
    setSubject('')
    reload()
  })

  return (
    <div className={styles.section}>
      {admin && (
        <Card>
          <form
            className={styles.form}
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim()) {
                action.run('create', () =>
                  createClass(academy.id, { name: name.trim(), subject: subject.trim() }),
                )
              }
            }}
          >
            <h2 className={styles.sectionTitle}>새 반 만들기</h2>
            <div className={styles.inline}>
              <Input
                label="반 이름"
                placeholder="예: 토요일 입시 A반"
                maxLength={50}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <Input
                label="과목 (선택)"
                placeholder="예: 기초디자인"
                maxLength={50}
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              />
              <button type="submit" className={styles.smallPrimary} disabled={!name.trim() || action.busy}>
                반 만들기
              </button>
            </div>
            {action.error && <p className={styles.error}>{action.error}</p>}
          </form>
        </Card>
      )}
      {error ? (
        <p className={styles.error}>{toErrorMessage(error)}</p>
      ) : !data ? (
        <p className={styles.hint}>불러오는 중…</p>
      ) : data.items.length === 0 ? (
        <p className={styles.empty}>{admin ? '아직 반이 없어요.' : '아직 담당 반이 없어요.'}</p>
      ) : (
        <ul className={styles.list}>
          {data.items.map((c) => (
            <li key={c.id} className={styles.row}>
              <Link to={`${base}/classes/${c.id}`} className={styles.rowLink}>
                <span className={styles.rowMain}>
                  <span className={styles.rowTitle}>
                    {c.name}
                    {c.subject ? ` · ${c.subject}` : ''}
                  </span>
                  <span className={styles.rowSub}>
                    학생 {c.student_count}명 · 담당{' '}
                    {c.instructors?.length ? c.instructors.map((i) => i.display_name).join(', ') : '없음'}
                  </span>
                </span>
                <span className={styles.link}>배정 관리 &gt;</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MembersTab({ academy, admin }) {
  const { profile } = useAuth()
  const load = useCallback(() => listMembers(academy.id), [academy.id])
  const { data, error, reload } = useAsync(load)
  const action = useAction(reload)
  const owner = academy.my_role === 'OWNER'

  if (error) return <p className={styles.error}>{toErrorMessage(error)}</p>
  if (!data) return <p className={styles.hint}>불러오는 중…</p>
  const order = ['OWNER', 'MANAGER', 'INSTRUCTOR', 'STUDENT']
  const members = [...data.items].sort((a, b) => order.indexOf(a.role) - order.indexOf(b.role))

  return (
    <div className={styles.section}>
      {action.error && <p className={styles.error}>{action.error}</p>}
      <ul className={styles.list}>
        {members.map((m) => (
          <li key={m.id} className={styles.row}>
            <span className={styles.rowMain}>
              <span className={styles.rowTitle}>{m.display_name}</span>
              <span className={styles.rowSub}>
                {ACADEMY_ROLE_LABELS[m.role]} · {formatDateTime(m.joined_at)} 소속
              </span>
            </span>
            <div className={styles.rowActions}>
              {owner && (m.role === 'INSTRUCTOR' || m.role === 'MANAGER') && (
                <button
                  type="button"
                  className={styles.smallButton}
                  disabled={action.busy !== null}
                  onClick={() =>
                    action.run(m.id, () =>
                      setMemberRole(academy.id, m.id, m.role === 'MANAGER' ? 'INSTRUCTOR' : 'MANAGER'),
                    )
                  }
                >
                  {m.role === 'MANAGER' ? '관리자 해제' : '관리자 지정'}
                </button>
              )}
              {admin && m.role !== 'OWNER' && m.user_id !== profile.id && (
                <button
                  type="button"
                  className={styles.smallButton}
                  disabled={action.busy !== null}
                  onClick={() => {
                    if (window.confirm(`${m.display_name}님을 학원에서 내보낼까요? 기록은 유지돼요.`)) {
                      action.run(m.id, () => removeMember(academy.id, m.id))
                    }
                  }}
                >
                  내보내기
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function RequestsTab({ academy }) {
  const load = useCallback(() => listJoinRequests(academy.id), [academy.id])
  const { data, error, reload } = useAsync(load)
  const action = useAction(reload)

  if (error) return <p className={styles.error}>{toErrorMessage(error)}</p>
  if (!data) return <p className={styles.hint}>불러오는 중…</p>
  if (data.items.length === 0) return <p className={styles.empty}>새 소속 신청이 없어요.</p>

  return (
    <div className={styles.section}>
      <p className={styles.hint}>승인하면 학원 멤버가 되고, 학생은 반에 배정해야 작품이 담당 강사에게 보여요.</p>
      {action.error && <p className={styles.error}>{action.error}</p>}
      <ul className={styles.list}>
        {data.items.map((r) => (
          <li key={r.id} className={styles.row}>
            <span className={styles.rowMain}>
              <span className={styles.rowTitle}>
                {r.applicant.display_name} · {ACADEMY_ROLE_LABELS[r.requested_role]}
              </span>
              <span className={styles.rowSub}>
                {formatDateTime(r.created_at)}
                {r.message ? ` · “${r.message}”` : ''}
              </span>
            </span>
            <div className={styles.rowActions}>
              <button
                type="button"
                className={styles.smallPrimary}
                disabled={action.busy !== null}
                onClick={() => action.run(r.id, () => reviewJoinRequest(academy.id, r.id, 'APPROVE'))}
              >
                승인
              </button>
              <button
                type="button"
                className={styles.smallButton}
                disabled={action.busy !== null}
                onClick={() => action.run(r.id, () => reviewJoinRequest(academy.id, r.id, 'REJECT'))}
              >
                거절
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

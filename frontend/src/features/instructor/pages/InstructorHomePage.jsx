import { useState } from 'react'
import { Navigate, useLocation, useOutletContext } from 'react-router-dom'
import { ACADEMY_STATUS_LABELS } from '../../../app/roles'
import { Button, Card, Input, Textarea } from '../../../components/ui'
import { toErrorMessage } from '../../../utils/errorMessages'
import { registerAcademy } from '../../academy/api'
import JoinAcademyPanel from '../../academy/JoinAcademyPanel'
import academyStyles from '../../academy/Academy.module.css'
import styles from '../Instructor.module.css'

const REQUEST_LABELS = { PENDING: '승인 대기', APPROVED: '승인됨', REJECTED: '거절됨' }

/**
 * /instructor: 운영 중 학원이 있으면 대시보드로, 없으면 학원 등록·소속 신청과 진행 상태.
 * /instructor/start: 이미 소속이 있어도 다른 학원을 등록·신청할 때.
 * 승인 전(등록 심사 중·소속 신청 대기)에는 학생 데이터 화면을 열지 않는다 (서버도 소속 기준으로 막음).
 */
export default function InstructorHomePage() {
  const { gate, reloadAcademies } = useOutletContext()
  const { pathname } = useLocation()

  if (gate.state === 'ready' && pathname === '/instructor') {
    return <Navigate to={`/instructor/academies/${gate.active[0].id}`} replace />
  }

  const excludeIds = [
    ...gate.active,
    ...gate.pendingAcademies,
    ...gate.pendingRequests.map((r) => ({ id: r.academy_id })),
  ].map((a) => a.id)

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <p className={styles.eyebrow}>ART MATE 강사</p>
          <h1 className={styles.title}>
            {gate.state === 'waiting' ? '승인을 기다리고 있어요' : '학원을 연결해 주세요'}
          </h1>
          <p className={styles.subtitle}>
            학원이 승인되거나 소속 신청이 승인되면 담당 학생의 작품과 첨삭을 볼 수 있어요.
          </p>
        </div>
      </div>

      <Progress gate={gate} />

      <div className={styles.grid}>
        <Card>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>기존 학원에 강사로 소속 신청</h2>
            <p className={styles.hint}>원장·관리자가 승인하면 소속돼요.</p>
            <JoinAcademyPanel excludeIds={excludeIds} onRequested={reloadAcademies} />
          </section>
        </Card>
        <Card>
          <RegisterAcademy onRegistered={reloadAcademies} />
        </Card>
      </div>
    </>
  )
}

function Progress({ gate }) {
  const rows = [
    ...gate.pendingAcademies.map((a) => ({
      key: `a-${a.id}`,
      title: a.name,
      detail: '학원 등록 신청 · ART MATE 운영팀 검토 중',
      badge: ACADEMY_STATUS_LABELS[a.status],
      tone: 'wait',
    })),
    ...gate.rejectedAcademies.map((a) => ({
      key: `a-${a.id}`,
      title: a.name,
      detail: '학원 등록 신청',
      badge: ACADEMY_STATUS_LABELS[a.status],
      tone: 'no',
    })),
    ...gate.pendingRequests.map((r) => ({
      key: `r-${r.id}`,
      title: r.academy_name,
      detail: '강사 소속 신청 · 원장·관리자 확인 중',
      badge: REQUEST_LABELS[r.status],
      tone: 'wait',
    })),
    ...gate.rejectedRequests.map((r) => ({
      key: `r-${r.id}`,
      title: r.academy_name,
      detail: r.review_note ? `소속 신청 · ${r.review_note}` : '소속 신청',
      badge: REQUEST_LABELS[r.status],
      tone: 'no',
    })),
  ]
  if (!rows.length) return null
  const badgeClass = { wait: academyStyles.badgeWait, no: academyStyles.badgeNo }
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>진행 상태</h2>
      <ul className={academyStyles.statusList}>
        {rows.map((row) => (
          <li key={row.key} className={academyStyles.statusItem}>
            <div className={academyStyles.resultMain}>
              <strong>{row.title}</strong>
              <span className={academyStyles.sub}>{row.detail}</span>
            </div>
            <span className={badgeClass[row.tone]}>{row.badge}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function RegisterAcademy({ onRegistered }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    setError('')
    try {
      await registerAcademy({ name: name.trim(), description: description.trim() })
      setDone(true)
      setName('')
      setDescription('')
      onRegistered?.()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className={styles.section} onSubmit={handleSubmit} noValidate>
      <h2 className={styles.sectionTitle}>새 학원 등록 신청 (원장)</h2>
      <p className={styles.hint}>
        신청하면 원장으로 등록되고, ART MATE 운영팀이 확인한 뒤 학생·강사가 소속을 신청할 수 있어요.
      </p>
      <Input
        label="학원 이름"
        placeholder="예: 아트메이트 미술학원"
        maxLength={100}
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <Textarea
        label="소개 (선택)"
        placeholder="지역, 주요 실기 유형 등"
        maxLength={500}
        rows={3}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      {error && <p className={styles.error}>{error}</p>}
      {done && <p className={styles.hint}>등록 신청을 보냈어요. 위 진행 상태에서 확인할 수 있어요.</p>}
      <Button type="submit" size="md" disabled={!name.trim() || busy}>
        {busy ? '신청하는 중…' : '등록 신청'}
      </Button>
    </form>
  )
}

import { useState } from 'react'
import { Search } from 'lucide-react'
import { Button, Input } from '../../components/ui'
import { toErrorMessage } from '../../utils/errorMessages'
import { requestJoin, searchAcademies } from './api'
import styles from './Academy.module.css'

/**
 * 승인된 학원을 이름으로 찾아 소속 신청 (학생·강사 공통).
 * 신청 역할은 서버가 계정 유형으로 정한다. 원장·관리자가 승인하면 소속된다.
 * excludeIds: 이미 소속·신청한 학원, onRequested: 신청 후 목록 다시 불러오기
 */
export default function JoinAcademyPanel({ excludeIds = [], onRequested }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')
  const [done, setDone] = useState([])

  async function handleSearch(e) {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    setError('')
    setBusy('search')
    try {
      setResults((await searchAcademies(q)).items)
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function handleRequest(academy) {
    setError('')
    setBusy(academy.id)
    try {
      await requestJoin(academy.id, message.trim())
      setDone((ids) => [...ids, academy.id])
      onRequested?.()
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  const visible = (results ?? []).filter((a) => !excludeIds.includes(a.id) || done.includes(a.id))

  return (
    <div className={styles.panel}>
      <form className={styles.searchRow} onSubmit={handleSearch} role="search">
        <Input
          label="학원 이름"
          icon={Search}
          placeholder="예: 아트메이트 미술학원"
          maxLength={50}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button type="submit" size="md" variant="dark" fullWidth={false} disabled={!query.trim() || busy === 'search'}>
          {busy === 'search' ? '찾는 중…' : '찾기'}
        </Button>
      </form>
      <Input
        label="원장님께 남길 말 (선택)"
        placeholder="예: 토요일 입시반 김서연입니다"
        maxLength={200}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
      />
      {error && <p className={styles.error}>{error}</p>}
      {results &&
        (visible.length === 0 ? (
          <p className={styles.empty}>찾는 학원이 없어요. 이름을 다시 확인해 주세요.</p>
        ) : (
          <ul className={styles.results}>
            {visible.map((academy) => (
              <li key={academy.id} className={styles.result}>
                <div className={styles.resultMain}>
                  <strong>{academy.name}</strong>
                  {academy.description && <span className={styles.sub}>{academy.description}</span>}
                </div>
                {done.includes(academy.id) ? (
                  <span className={styles.requested}>신청함</span>
                ) : (
                  <Button
                    size="md"
                    variant="soft"
                    fullWidth={false}
                    disabled={busy !== null}
                    onClick={() => handleRequest(academy)}
                  >
                    {busy === academy.id ? '신청하는 중…' : '소속 신청'}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ))}
    </div>
  )
}

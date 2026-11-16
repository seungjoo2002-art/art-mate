import { useCallback } from 'react'
import { Select } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { listClasses, listMyAcademies } from './api'

/**
 * v1.0 학생: 작품을 학원·반에 연결 (선택). 소속 학원이 없으면 아무것도 보이지 않는다.
 * 학원에 연결한 작품은 담당 강사가 보고 AI 첨삭 정리를 검토·승인한다 (개인 작품은 본인 확정).
 * value: { academyId, classId }, onChange(next)
 */
export default function AcademyClassPicker({ value, onChange }) {
  const loadAcademies = useCallback(
    () =>
      listMyAcademies().then((page) =>
        page.items.filter((a) => a.status === 'ACTIVE' && a.my_role === 'STUDENT'),
      ),
    [],
  )
  const { data: academies } = useAsync(loadAcademies)
  const loadClasses = useCallback(
    () => (value.academyId ? listClasses(value.academyId).then((p) => p.items) : Promise.resolve([])),
    [value.academyId],
  )
  const { data: classes } = useAsync(loadClasses)

  if (!academies?.length) return null
  return (
    <>
      <Select
        label="학원 (선택)"
        placeholder="개인 작품 (학원에 연결하지 않음)"
        options={academies.map((a) => ({ code: a.id, label: a.name }))}
        value={value.academyId ?? ''}
        onChange={(e) => onChange({ academyId: e.target.value || null, classId: null })}
      />
      {value.academyId && classes?.length > 0 && (
        <Select
          label="반 (선택)"
          placeholder="반 선택 안 함"
          options={classes.map((c) => ({ code: c.id, label: c.name }))}
          value={value.classId ?? ''}
          onChange={(e) => onChange({ ...value, classId: e.target.value || null })}
        />
      )}
    </>
  )
}

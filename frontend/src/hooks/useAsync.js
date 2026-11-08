import { useCallback, useEffect, useState } from 'react'

/**
 * 비동기 데이터 로드. load는 useCallback으로 감싸서 넘길 것 (바뀌면 다시 불러옴)
 * reload 중에도 이전 data를 유지해서 화면이 깜빡이지 않음
 */
export function useAsync(load) {
  const [reloadKey, setReloadKey] = useState(0)
  const [state, setState] = useState({ load: null, reloadKey: -1, data: undefined, error: null })

  useEffect(() => {
    let cancelled = false
    load().then(
      (data) => !cancelled && setState({ load, reloadKey, data, error: null }),
      (error) => !cancelled && setState({ load, reloadKey, data: undefined, error }),
    )
    return () => {
      cancelled = true
    }
  }, [load, reloadKey])

  const reload = useCallback(() => setReloadKey((key) => key + 1), [])
  const loading = state.load !== load || state.reloadKey !== reloadKey

  return { data: state.data, error: loading ? null : state.error, loading, reload }
}

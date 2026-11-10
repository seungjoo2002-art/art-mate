import { useAsync } from './useAsync'
import { getOptions } from '../lib/options'

/** 서버 선택지. 받기 전에는 undefined */
export function useOptions() {
  return useAsync(getOptions).data
}

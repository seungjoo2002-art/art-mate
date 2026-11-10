import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// .env.local이 없으면 null — 앱 전체가 죽지 않고 AuthProvider가 설정 안내 화면을 보여 줌
export const supabase = url && anonKey ? createClient(url, anonKey) : null

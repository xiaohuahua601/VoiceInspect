export const apiBase = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'

export type User = { id: string; username: string; role: string; status?: string; must_change_password?: boolean; organization_id?: string | null; scopes?: Array<{ organization_id: string; site_id?: string | null; line_id?: string | null }> }
export type Device = { id: string; code: string; name: string; model: string; organization_id?: string | null; site_id?: string | null; line_id?: string | null; metadata?: Record<string, unknown>; created_at?: string }
export type Fault = { id: string; device_id: string; session_id?: string | null; symptom: string; severity: string; status: string; creator_id: string; assigned_to?: string | null; assigned_to_name?: string | null; resolution?: string | null; created_at: string; updated_at?: string }
export type KnowledgeDoc = { id: string; name: string; version: string; status: string; organization_id?: string | null; failure_reason?: string | null; metadata?: Record<string, unknown>; chunks: number; created_at: string }
export type AuditEvent = { id: string; trace_id: string; actor_id?: string; action: string; target?: string; result: string; details?: Record<string, unknown>; created_at: string }
export type Session = { id: string; title: string; status: string; device_id?: string | null; created_at: string; updated_at?: string }
export type Provider = { name: string; model?: string | null; enabled: boolean }

export function getToken() { return localStorage.getItem('voiceinspect_token') ?? '' }
export function getStoredUser(): User | null {
  try { return JSON.parse(localStorage.getItem('voiceinspect_user') ?? 'null') } catch { return null }
}
export function setAuth(token: string, user: User) {
  localStorage.setItem('voiceinspect_token', token)
  localStorage.setItem('voiceinspect_user', JSON.stringify(user))
}
export function clearAuth() {
  localStorage.removeItem('voiceinspect_token')
  localStorage.removeItem('voiceinspect_user')
}
export function roleLabel(role?: string) {
  return ({ operator: '操作员', maintenance_supervisor: '维修主管', knowledge_admin: '知识管理员', system_admin: '系统管理员' } as Record<string, string>)[role ?? ''] ?? role ?? '未登录'
}
export function canAccess(role: string | undefined, roles?: string[]) {
  return !roles?.length || Boolean(role && roles.includes(role))
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${apiBase}${path}`, { ...options, headers })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = data?.error
    const err = new Error(error?.message ?? '服务暂时不可用')
    ;(err as Error & { code?: string; status?: number }).code = error?.code
    ;(err as Error & { code?: string; status?: number }).status = response.status
    throw err
  }
  return data as T
}
export function fileUrl(path: string) { return `${apiBase}${path}` }

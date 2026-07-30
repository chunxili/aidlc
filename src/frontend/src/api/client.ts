/**
 * 统一请求封装。
 *
 * 设计依据：frontend-design.md 第五节。
 * 关键约定：**按 code 而非 message 分支** —— 文案可调整，code 是契约。
 */

const TOKEN_KEY = 'coupon_token'
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || ''

export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

let onUnauthenticated: (() => void) | null = null
export function setUnauthenticatedHandler(fn: () => void) {
  onUnauthenticated = fn
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (resp.status === 204) return undefined as T

  let payload: unknown = null
  try {
    payload = await resp.json()
  } catch {
    payload = null
  }

  if (!resp.ok) {
    const p = (payload ?? {}) as { code?: string; message?: string }
    // 401 一律清除本地凭证并回登录页；403 交由页面处理
    // （越权与风控都是 403，靠 code 区分）
    if (resp.status === 401) {
      tokenStore.clear()
      onUnauthenticated?.()
    }
    throw new ApiError(resp.status, p.code ?? 'ERROR', p.message ?? '请求失败')
  }
  return payload as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
}

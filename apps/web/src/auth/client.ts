/** Replaceable same-origin API boundary; COD-356 can swap its transport later. */
export type PrivateSession = {
  authenticated: true
  csrf_token: string
}

export type XConnection = {
  connected: boolean
  state: string | null
  scopes: string[]
  expires_at: string | null
}

export class ApiResponseError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string) {
    super(code)
    this.name = 'ApiResponseError'
    this.status = status
    this.code = code
  }
}

let csrfToken: string | null = null

function setCsrfToken(value: string | null) {
  csrfToken = value
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type'))
    headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET' && csrfToken)
    headers.set('X-CSRF-Token', csrfToken)

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: 'same-origin',
  })

  if (!response.ok) {
    let code = 'request_failed'
    try {
      const payload = (await response.json()) as {
        error?: { code?: unknown }
      }
      if (typeof payload.error?.code === 'string') code = payload.error.code
    } catch {
      // Keep the transport failure generic when the server did not return JSON.
    }
    if (
      response.status === 401 &&
      (code === 'authentication_required' || code === 'session_invalid')
    )
      setCsrfToken(null)
    throw new ApiResponseError(response.status, code)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const authApi = {
  async readSession(signal?: AbortSignal) {
    try {
      const session = await request<PrivateSession>('/api/auth/session', {
        signal,
      })
      setCsrfToken(session.csrf_token)
      return session
    } catch (error) {
      if (error instanceof ApiResponseError && error.status === 401)
        setCsrfToken(null)
      throw error
    }
  },

  async createPrivateSession(secret: string, signal?: AbortSignal) {
    const session = await request<PrivateSession>('/api/auth/private/session', {
      method: 'POST',
      body: JSON.stringify({ secret }),
      signal,
    })
    setCsrfToken(session.csrf_token)
    return session
  },

  async readXConnection(signal?: AbortSignal) {
    return request<XConnection>('/api/auth/x/connection', { signal })
  },

  async refreshXConnection(signal?: AbortSignal) {
    const connection = await request<XConnection>('/api/auth/x/refresh', {
      method: 'POST',
      body: '{}',
      signal,
    })
    return connection
  },

  async disconnectXConnection(signal?: AbortSignal) {
    await request<void>('/api/auth/x/disconnect', {
      method: 'POST',
      body: '{}',
      signal,
    })
  },

  async logout(signal?: AbortSignal) {
    await request<void>('/api/auth/logout', {
      method: 'POST',
      body: '{}',
      signal,
    })
    setCsrfToken(null)
  },
}

export function getXAuthorizationUrl() {
  const returnPath = '/connections'
  const query = new URLSearchParams({ return_to: returnPath })
  return `/api/auth/x/authorize?${query.toString()}`
}

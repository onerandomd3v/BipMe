import createClient from 'openapi-fetch'
import type { components, paths } from './generated/schema'

type ErrorResponse = components['schemas']['ErrorResponse']
type ValidationError = components['schemas']['ValidationError']

export type ApiErrorPayload = ErrorResponse | { detail?: ValidationError[] }

export type RateLimitInfo = {
  limit: number | null
  remaining: number | null
  resetAt: Date | null
  retryAfterAt: Date | null
  retryAfterSeconds: number | null
}

class ResponseParseError extends Error {
  readonly status: number

  constructor(status: number) {
    super('The API returned invalid JSON.')
    this.name = 'ResponseParseError'
    this.status = status
  }
}

export class ApiRequestError extends Error {
  readonly status: number | null
  readonly code: string
  readonly details: unknown
  readonly payload: unknown
  readonly rateLimit: RateLimitInfo | null

  constructor(options: {
    code: string
    details?: unknown
    message: string
    payload?: unknown
    rateLimit?: RateLimitInfo | null
    status: number | null
  }) {
    super(options.message)
    this.name = 'ApiRequestError'
    this.code = options.code
    this.details = options.details ?? null
    this.payload = options.payload ?? null
    this.rateLimit = options.rateLimit ?? null
    this.status = options.status
  }
}

export type ApiClient = ReturnType<typeof createApiClient>

type CreatorProfileUpdate = components['schemas']['CreatorProfileUpdate']
type CreatorProfileState = components['schemas']['CreatorProfileStateResponse']
type CreatorProfile = components['schemas']['CreatorProfileResponse']
type DataPermission = components['schemas']['DataPermissionResponse']
type DataPermissionUpdate = components['schemas']['DataPermissionUpdate']
type CreatorReport = components['schemas']['CreatorReportResponse']
type CreatorReportState = components['schemas']['CreatorReportStateResponse']

function numberHeader(response: Response, name: string) {
  const value = response.headers.get(name)
  if (!value) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function rateLimitInfo(response: Response): RateLimitInfo | null {
  const retryAfter = response.headers.get('Retry-After')
  const retryAfterSeconds =
    retryAfter && Number.isFinite(Number(retryAfter))
      ? Number(retryAfter)
      : null
  const retryAfterAt =
    retryAfter && retryAfterSeconds === null ? new Date(retryAfter) : null
  const validRetryAfterAt =
    retryAfterAt && !Number.isNaN(retryAfterAt.getTime()) ? retryAfterAt : null
  const limit = numberHeader(response, 'X-RateLimit-Limit')
  const remaining = numberHeader(response, 'X-RateLimit-Remaining')
  const reset = numberHeader(response, 'X-RateLimit-Reset')
  if (
    retryAfterSeconds === null &&
    validRetryAfterAt === null &&
    limit === null &&
    remaining === null &&
    reset === null
  )
    return null
  return {
    limit,
    remaining,
    resetAt: reset === null ? null : new Date(reset * 1000),
    retryAfterAt: validRetryAfterAt,
    retryAfterSeconds,
  }
}

function errorFromResponse(response: Response, payload: unknown) {
  const error =
    payload && typeof payload === 'object' && 'error' in payload
      ? (
          payload as {
            error?: { code?: unknown; message?: unknown; fields?: unknown }
          }
        ).error
      : null
  const validation =
    payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : null
  const code =
    typeof error?.code === 'string'
      ? error.code
      : Array.isArray(validation)
        ? 'validation_error'
        : `http_${response.status}`
  const message =
    typeof error?.message === 'string'
      ? error.message
      : Array.isArray(validation)
        ? 'The request was invalid.'
        : response.statusText || 'The request failed.'
  return new ApiRequestError({
    code,
    details: error?.fields ?? validation,
    message,
    payload,
    rateLimit: rateLimitInfo(response),
    status: response.status,
  })
}

async function parsePayload(response: Response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isSessionResponse(
  value: unknown,
): value is components['schemas']['SessionResponse'] {
  return Boolean(
    value &&
    typeof value === 'object' &&
    typeof (value as { authenticated?: unknown }).authenticated === 'boolean' &&
    typeof (value as { csrf_token?: unknown }).csrf_token === 'string',
  )
}

function isHealthResponse(value: unknown): value is Record<string, string> {
  return Boolean(
    value &&
    typeof value === 'object' &&
    typeof (value as { status?: unknown }).status === 'string',
  )
}

export function createApiClient(fetchImplementation: typeof fetch = fetch) {
  let csrfToken: string | null = null
  const sessionInvalidationListeners = new Set<() => void>()

  const clearSessionState = () => {
    csrfToken = null
    sessionInvalidationListeners.forEach((listener) => listener())
  }

  const invalidateSessionAfterAuthFailure = (error: unknown) => {
    if (!(error instanceof ApiRequestError)) return
    const confirmedSessionFailure =
      error.status === 401 ||
      (error.status === 403 &&
        [
          'csrf_validation_failed',
          'session_invalid',
          'session_expired',
        ].includes(error.code))
    if (confirmedSessionFailure) clearSessionState()
  }

  const client = createClient<paths>({
    baseUrl:
      typeof location === 'undefined' ? 'http://localhost' : location.origin,
    credentials: 'same-origin',
    fetch: async (request) => {
      const headers = new Headers(request.headers)
      if (csrfToken && request.method !== 'GET' && request.method !== 'HEAD') {
        headers.set('X-CSRF-Token', csrfToken)
      }
      const response = await fetchImplementation(
        new Request(request, {
          credentials: 'same-origin',
          headers,
          signal: request.signal,
        }),
      )
      if (response.ok && response.status !== 204 && request.method !== 'HEAD') {
        try {
          await response.clone().json()
        } catch {
          throw new ResponseParseError(response.status)
        }
      }
      return response
    },
  })

  async function unwrap<T>(
    result: { data?: T; error?: unknown; response: Response },
    allowEmpty = false,
  ) {
    if (!result.response.ok) {
      const payload = result.error ?? (await parsePayload(result.response))
      const error = errorFromResponse(result.response, payload)
      invalidateSessionAfterAuthFailure(error)
      throw error
    }
    if (result.data === undefined && !allowEmpty) {
      throw new ApiRequestError({
        code: 'malformed_response',
        message: 'The API returned an empty response.',
        status: result.response.status,
      })
    }
    return result.data as T
  }

  async function request<T>(operation: () => Promise<T>, signal?: AbortSignal) {
    try {
      return await operation()
    } catch (error) {
      if (signal?.aborted) throw error
      if (error instanceof ResponseParseError) {
        throw new ApiRequestError({
          code: 'malformed_response',
          message: error.message,
          status: error.status,
        })
      }
      if (
        error &&
        typeof error === 'object' &&
        'name' in error &&
        error.name === 'AbortError'
      ) {
        throw error
      }
      if (error instanceof ApiRequestError) throw error
      throw new ApiRequestError({
        code: 'network_error',
        message: 'The API could not be reached.',
        status: null,
      })
    }
  }

  return {
    async health(signal?: AbortSignal) {
      const result = await request(
        () => client.GET('/api/health', { signal }),
        signal,
      )
      const data = await unwrap(result)
      if (!isHealthResponse(data)) {
        throw new ApiRequestError({
          code: 'malformed_response',
          message: 'The health response was invalid.',
          status: result.response.status,
        })
      }
      return data
    },
    async session(signal?: AbortSignal) {
      try {
        const result = await request(
          () => client.GET('/api/auth/session', { signal }),
          signal,
        )
        const data = await unwrap(result)
        if (!isSessionResponse(data)) {
          throw new ApiRequestError({
            code: 'malformed_response',
            message: 'The session response was invalid.',
            status: result.response.status,
          })
        }
        if (!data.authenticated) clearSessionState()
        csrfToken = data.csrf_token
        return data
      } catch (error) {
        invalidateSessionAfterAuthFailure(error)
        throw error
      }
    },
    async privateSession(secret: string, signal?: AbortSignal) {
      const result = await request(
        () =>
          client.POST('/api/auth/private/session', {
            body: { secret },
            signal,
          }),
        signal,
      )
      const data = await unwrap(result)
      if (!isSessionResponse(data)) {
        throw new ApiRequestError({
          code: 'malformed_response',
          message: 'The session response was invalid.',
          status: result.response.status,
        })
      }
      clearSessionState()
      csrfToken = data.csrf_token
      return data
    },
    async logout(signal?: AbortSignal) {
      try {
        const result = await request(
          () => client.POST('/api/auth/logout', { signal }),
          signal,
        )
        await unwrap(result, true)
        clearSessionState()
      } catch (error) {
        invalidateSessionAfterAuthFailure(error)
        throw error
      }
    },
    async profile(signal?: AbortSignal): Promise<CreatorProfileState> {
      const result = await request(
        () => client.GET('/api/v1/creators/me/profile', { signal }),
        signal,
      )
      return unwrap(result)
    },
    async saveProfile(
      body: CreatorProfileUpdate,
      signal?: AbortSignal,
    ): Promise<CreatorProfile> {
      const result = await request(
        () => client.PUT('/api/v1/creators/me/profile', { body, signal }),
        signal,
      )
      return unwrap(result)
    },
    async dataPermissions(signal?: AbortSignal): Promise<DataPermission> {
      const result = await request(
        () => client.GET('/api/v1/creators/me/data-permissions', { signal }),
        signal,
      )
      return unwrap(result)
    },
    async saveDataPermissions(
      body: DataPermissionUpdate,
      signal?: AbortSignal,
    ): Promise<DataPermission> {
      const result = await request(
        () =>
          client.PUT('/api/v1/creators/me/data-permissions', { body, signal }),
        signal,
      )
      return unwrap(result)
    },
    async latestReport(signal?: AbortSignal): Promise<CreatorReportState> {
      const result = await request(
        () => client.GET('/api/v1/creators/me/report/latest', { signal }),
        signal,
      )
      return unwrap(result)
    },
    async generateReport(
      body: components['schemas']['CreatorReportRequest'],
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<CreatorReport> {
      const result = await request(
        () =>
          client.POST('/api/v1/creators/me/report', {
            body,
            params: { header: { 'Idempotency-Key': idempotencyKey } },
            signal,
          }),
        signal,
      )
      return unwrap(result)
    },
    async report(
      reportId: string,
      signal?: AbortSignal,
    ): Promise<CreatorReport> {
      const result = await request(
        () =>
          client.GET('/api/v1/creators/me/reports/{report_id}', {
            params: { path: { report_id: reportId } },
            signal,
          }),
        signal,
      )
      return unwrap(result)
    },
    async deleteReports(signal?: AbortSignal): Promise<void> {
      const result = await request(
        () => client.DELETE('/api/v1/creators/me/reports', { signal }),
        signal,
      )
      await unwrap(result, true)
    },
    getCsrfToken() {
      return csrfToken
    },
    subscribeSessionInvalidation(listener: () => void) {
      sessionInvalidationListeners.add(listener)
      return () => {
        sessionInvalidationListeners.delete(listener)
      }
    },
    raw: client,
  }
}

export const apiClient = createApiClient()

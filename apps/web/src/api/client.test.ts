import { setupServer } from 'msw/node'
import {
  beforeAll,
  beforeEach,
  afterAll,
  afterEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import { ApiRequestError, createApiClient } from './client'
import { apiHandlers } from './mocks'
import { errorFixture } from './fixtures'
import { http, HttpResponse } from 'msw'

function response(body: unknown, status = 200, headers?: HeadersInit) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function historyImport(status: string) {
  return {
    import_id: 'cod-357-test-import',
    status,
    requested_posts: 20,
    pages_read: status === 'running' ? 0 : 1,
    imported_posts: status === 'partial' || status === 'complete' ? 12 : 0,
    next_page_available: status === 'partial',
    error_code: status === 'unavailable' ? 'external_gate_unverified' : null,
    source: 'x_creator_authorized_history',
    started_at: '2026-11-10T09:00:00Z',
    completed_at: status === 'running' ? null : '2026-11-10T09:01:00Z',
    provenance: { provider: 'x', endpoint: 'fixture' },
  }
}

describe('API client', () => {
  const fetchMock = vi.fn<typeof fetch>()
  const server = setupServer(...apiHandlers)

  beforeAll(() => server.listen())
  afterAll(() => server.close())
  beforeEach(() => fetchMock.mockReset())
  afterEach(() => server.resetHandlers())

  it('uses isolated MSW handlers for synthetic health and session responses', async () => {
    const client = createApiClient()
    await expect(client.health()).resolves.toEqual({ status: 'ok' })
    await expect(client.session()).resolves.toMatchObject({
      authenticated: true,
    })

    server.use(
      http.get('*/api/auth/session', () =>
        HttpResponse.json(errorFixture, { status: 401 }),
      ),
    )
    await expect(client.session()).rejects.toMatchObject({
      status: 401,
      code: 'authentication_required',
    })
  })

  it('uses generated report endpoints with synthetic MSW contracts', async () => {
    const client = createApiClient()
    await client.session()
    await expect(client.profile()).resolves.toMatchObject({
      status: 'configured',
      profile: { niche: 'Independent product design' },
    })
    await expect(client.dataPermissions()).resolves.toMatchObject({
      niche_discovery: 'unavailable',
      external_synthesis: 'disabled',
    })
    await expect(client.latestReport()).resolves.toMatchObject({
      status: 'available',
      latest_report: { coverage: 'personal_only_partial' },
    })
    await expect(
      client.generateReport({ data_sources: [] }, 'cod-379-fixture-key'),
    ).resolves.toMatchObject({ id: '00000000-0000-0000-0000-000000000380' })
    await expect(client.deleteReports()).resolves.toBeUndefined()
  })

  it('uses same-origin cookies and returns typed health data', async () => {
    fetchMock.mockResolvedValue(response({ status: 'ok' }))
    const client = createApiClient(fetchMock)
    await expect(client.health()).resolves.toEqual({ status: 'ok' })
    expect(fetchMock.mock.calls[0]?.[0]).toBeInstanceOf(Request)
    expect((fetchMock.mock.calls[0]?.[0] as Request).credentials).toBe(
      'same-origin',
    )
  })

  it.each(['running', 'partial', 'complete', 'unavailable'])(
    'returns the server-reported history import state: %s',
    async (status) => {
      fetchMock.mockResolvedValueOnce(response(historyImport(status)))
      const client = createApiClient(fetchMock)
      await expect(
        client.historyImportStatus('cod-357-test-import'),
      ).resolves.toMatchObject({
        import_id: 'cod-357-test-import',
        status,
        imported_posts: status === 'partial' || status === 'complete' ? 12 : 0,
      })
      const request = fetchMock.mock.calls[0]?.[0] as Request
      expect(request.method).toBe('GET')
      expect(decodeURIComponent(new URL(request.url).pathname)).toBe(
        '/api/v1/creators/me/history/imports/cod-357-test-import',
      )
      expect(request.credentials).toBe('same-origin')
    },
  )

  it('retries a history import with the same id and does not create a new import identity', async () => {
    fetchMock
      .mockResolvedValueOnce(
        response({ authenticated: true, csrf_token: 'history-csrf' }),
      )
      .mockResolvedValueOnce(
        response({ error: { code: 'history_import_unavailable' } }, 503),
      )
      .mockResolvedValueOnce(response(historyImport('complete')))
    const client = createApiClient(fetchMock)
    await client.session()
    const requestBody = {
      import_id: 'cod-357-test-import',
      max_posts: 20,
    } as const
    await expect(client.startHistoryImport(requestBody)).rejects.toMatchObject({
      status: 503,
      code: 'history_import_unavailable',
    })
    await expect(client.startHistoryImport(requestBody)).resolves.toMatchObject(
      {
        status: 'complete',
      },
    )

    const first = fetchMock.mock.calls[1]?.[0] as Request
    const retry = fetchMock.mock.calls[2]?.[0] as Request
    expect(first.method).toBe('POST')
    expect(retry.method).toBe('POST')
    expect(first.url).toBe(retry.url)
    expect(await first.clone().json()).toEqual(await retry.clone().json())
    expect(first.headers.get('X-CSRF-Token')).toBe('history-csrf')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('resumes a known import by reading status with its existing id', async () => {
    fetchMock
      .mockResolvedValueOnce(response(historyImport('running')))
      .mockResolvedValueOnce(response(historyImport('complete')))
    const client = createApiClient(fetchMock)
    await expect(
      client.historyImportStatus('cod-357-test-import'),
    ).resolves.toMatchObject({ status: 'running' })
    await expect(
      client.historyImportStatus('cod-357-test-import'),
    ).resolves.toMatchObject({ status: 'complete' })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(
      fetchMock.mock.calls.map(([input]) => (input as Request).method),
    ).toEqual(['GET', 'GET'])
  })

  it('rejects malformed import status without making another request', async () => {
    fetchMock.mockResolvedValueOnce(response({ import_id: 'partial' }))
    const client = createApiClient(fetchMock)
    await expect(
      client.historyImportStatus('cod-357-test-import'),
    ).rejects.toMatchObject({
      code: 'malformed_response',
    })
    await expect(
      client.historyImportStatus('../outside'),
    ).rejects.toMatchObject({
      code: 'invalid_import_id',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('stores CSRF in memory and sends it on unsafe calls', async () => {
    fetchMock
      .mockResolvedValueOnce(
        response({ authenticated: true, csrf_token: 'csrf' }),
      )
      .mockResolvedValueOnce(response(null, 204))
    const client = createApiClient(fetchMock)
    await client.session()
    await client.logout()
    expect(
      (fetchMock.mock.calls[1]?.[0] as Request).headers.get('X-CSRF-Token'),
    ).toBe('csrf')
  })

  it('clears CSRF in memory after a confirmed session failure', async () => {
    fetchMock
      .mockResolvedValueOnce(
        response({ authenticated: true, csrf_token: 'csrf' }),
      )
      .mockResolvedValueOnce(
        response(
          { error: { code: 'session_invalid', message: 'Expired' } },
          401,
        ),
      )
    const client = createApiClient(fetchMock)
    await client.session()
    await expect(client.session()).rejects.toMatchObject({ status: 401 })
    expect(client.getCsrfToken()).toBeNull()
  })

  it('keeps CSRF for unrelated permission denials', async () => {
    fetchMock
      .mockResolvedValueOnce(
        response({ authenticated: true, csrf_token: 'csrf' }),
      )
      .mockResolvedValueOnce(
        response(
          { error: { code: 'creator_forbidden', message: 'Forbidden' } },
          403,
        ),
      )
    const client = createApiClient(fetchMock)
    await client.session()
    await expect(client.profile()).rejects.toMatchObject({
      status: 403,
      code: 'creator_forbidden',
    })
    expect(client.getCsrfToken()).toBe('csrf')
  })

  it('notifies subscribers when the authenticated session is invalidated', async () => {
    fetchMock
      .mockResolvedValueOnce(
        response({ authenticated: true, csrf_token: 'csrf' }),
      )
      .mockResolvedValueOnce(
        response(
          { error: { code: 'session_expired', message: 'Expired' } },
          401,
        ),
      )
    const client = createApiClient(fetchMock)
    const invalidated = vi.fn()
    client.subscribeSessionInvalidation(invalidated)
    await client.session()
    await expect(client.profile()).rejects.toMatchObject({ status: 401 })
    expect(invalidated).toHaveBeenCalledTimes(1)
    expect(client.getCsrfToken()).toBeNull()
  })

  it('notifies subscribers after confirmed logout', async () => {
    fetchMock
      .mockResolvedValueOnce(
        response({ authenticated: true, csrf_token: 'csrf' }),
      )
      .mockResolvedValueOnce(response(null, 204))
    const client = createApiClient(fetchMock)
    const invalidated = vi.fn()
    client.subscribeSessionInvalidation(invalidated)
    await client.session()
    await client.logout()
    expect(invalidated).toHaveBeenCalledTimes(1)
    expect(client.getCsrfToken()).toBeNull()
  })

  it.each([
    [401, 'authentication_required'],
    [403, 'csrf_validation_failed'],
    [409, 'assessment_conflict'],
  ])('preserves %s API errors', async (status, code) => {
    fetchMock.mockResolvedValue(
      response({ error: { code, message: 'Failure', fields: null } }, status),
    )
    await expect(createApiClient(fetchMock).health()).rejects.toMatchObject({
      status,
      code,
    })
  })

  it('preserves validation details and rate-limit headers', async () => {
    fetchMock.mockResolvedValue(
      response(
        {
          error: {
            code: 'invalid_request',
            message: 'Request validation failed.',
            fields: [{ field: 'body.secret', code: 'missing' }],
          },
        },
        422,
        {
          'Retry-After': '30',
          'X-RateLimit-Limit': '10',
          'X-RateLimit-Remaining': '0',
        },
      ),
    )
    await expect(createApiClient(fetchMock).health()).rejects.toMatchObject({
      code: 'invalid_request',
      details: [{ field: 'body.secret', code: 'missing' }],
      rateLimit: { limit: 10, remaining: 0, retryAfterSeconds: 30 },
    })
  })

  it('preserves HTTP-date Retry-After values', async () => {
    fetchMock.mockResolvedValue(
      response({ error: { code: 'rate_limited', message: 'Try later' } }, 429, {
        'Retry-After': 'Wed, 21 Oct 2015 07:28:00 GMT',
      }),
    )
    await expect(createApiClient(fetchMock).health()).rejects.toMatchObject({
      rateLimit: {
        retryAfterAt: new Date('Wed, 21 Oct 2015 07:28:00 GMT'),
        retryAfterSeconds: null,
      },
    })
  })

  it('rejects malformed success payloads and network failures', async () => {
    fetchMock.mockResolvedValueOnce(response({ nope: true }))
    await expect(createApiClient(fetchMock).health()).rejects.toMatchObject({
      code: 'malformed_response',
    })

    fetchMock.mockResolvedValueOnce(
      new Response('{not-json', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(createApiClient(fetchMock).health()).rejects.toMatchObject({
      code: 'malformed_response',
      status: 200,
    })

    fetchMock.mockRejectedValueOnce(new TypeError('network down'))
    await expect(createApiClient(fetchMock).health()).rejects.toMatchObject({
      code: 'network_error',
      status: null,
    })
  })

  it('passes AbortSignal through and preserves abort errors', async () => {
    const controller = new AbortController()
    controller.abort()
    fetchMock.mockImplementationOnce(async (input) => {
      expect((input as Request).signal.aborted).toBe(true)
      throw new DOMException('The operation was aborted.', 'AbortError')
    })
    await expect(
      createApiClient(fetchMock).health(controller.signal),
    ).rejects.toMatchObject({
      name: 'AbortError',
    })
  })

  it('exposes a normalized error type for HTTP failures', async () => {
    fetchMock.mockResolvedValue(
      response({ error: { code: 'rate_limited', message: 'Try later' } }, 429),
    )
    await expect(createApiClient(fetchMock).health()).rejects.toBeInstanceOf(
      ApiRequestError,
    )
  })
})

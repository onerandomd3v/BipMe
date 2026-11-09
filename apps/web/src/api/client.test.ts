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

  it('uses same-origin cookies and returns typed health data', async () => {
    fetchMock.mockResolvedValue(response({ status: 'ok' }))
    const client = createApiClient(fetchMock)
    await expect(client.health()).resolves.toEqual({ status: 'ok' })
    expect(fetchMock.mock.calls[0]?.[0]).toBeInstanceOf(Request)
    expect((fetchMock.mock.calls[0]?.[0] as Request).credentials).toBe(
      'same-origin',
    )
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

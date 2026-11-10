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

  it('uses the typed assessment and publication endpoints through MSW', async () => {
    const client = createApiClient()
    await client.session()
    const assessmentId = '00000000-0000-4000-8000-000000000365'
    await expect(client.draftAssessment(assessmentId)).resolves.toMatchObject({
      assessment_id: assessmentId,
      input_fingerprint: 'sha256:cod-365-fixture',
    })
    await expect(client.publication(assessmentId)).resolves.toMatchObject({
      assessment_id: assessmentId,
      version_match_state: 'unknown',
    })
    await expect(
      client.linkPublication(assessmentId, {
        post_url_or_id: '1900000000000000001',
      }),
    ).resolves.toMatchObject({ assessment_id: assessmentId })
  })

  it('normalizes typed assessment and publication GET failures through MSW', async () => {
    const assessmentId = '00000000-0000-4000-8000-000000000365'
    server.use(
      http.get(`*/api/v1/creators/me/draft-assessments/${assessmentId}`, () =>
        HttpResponse.json(
          { error: { code: 'assessment_unavailable', message: 'Unavailable' } },
          { status: 503 },
        ),
      ),
    )
    const client = createApiClient()
    await expect(client.draftAssessment(assessmentId)).rejects.toMatchObject({
      status: 503,
      code: 'assessment_unavailable',
    })

    server.resetHandlers()
    server.use(
      http.get(
        `*/api/v1/creators/me/draft-assessments/${assessmentId}/publication`,
        () => new HttpResponse('{not-json', { status: 200 }),
      ),
    )
    await expect(client.publication(assessmentId)).rejects.toMatchObject({
      status: 200,
      code: 'malformed_response',
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

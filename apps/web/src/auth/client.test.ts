import { describe, expect, it } from 'vitest'
import { createApiClient } from '../api/client'
import { ApiResponseError, createAuthApi, getXAuthorizationUrl } from './client'

function createTestAuthApi(
  responder: (request: Request) => Response | Promise<Response>,
) {
  const requests: Request[] = []
  const fetchMock: typeof fetch = async (input) => {
    const request = input instanceof Request ? input : new Request(input)
    requests.push(request)
    return responder(request)
  }
  return { auth: createAuthApi(createApiClient(fetchMock)), requests }
}

function response(body: unknown, status = 200) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('Connections authentication client', () => {
  it('uses the generated client, same-origin cookies, and in-memory CSRF', async () => {
    const { auth, requests } = createTestAuthApi((request) => {
      const path = new URL(request.url).pathname
      if (path === '/api/auth/session')
        return response({ authenticated: true, csrf_token: 'csrf-test' })
      if (path === '/api/auth/x/refresh')
        return response({
          connected: true,
          state: 'connected',
          scopes: ['tweet.read'],
          expires_at: null,
        })
      throw new Error(`Unexpected request: ${path}`)
    })

    await auth.readSession()
    await auth.refreshXConnection()

    expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
      '/api/auth/session',
      '/api/auth/x/refresh',
    ])
    expect(requests[0]?.credentials).toBe('same-origin')
    expect(requests[1]?.credentials).toBe('same-origin')
    expect(requests[1]?.headers.get('X-CSRF-Token')).toBe('csrf-test')
    expect(requests[1]?.body).toBeNull()
  })

  it('sends the private-session secret in the request body only', async () => {
    const { auth, requests } = createTestAuthApi(() =>
      response({ authenticated: true, csrf_token: 'new-csrf' }),
    )

    await auth.createPrivateSession('temporary-test-secret')

    const request = requests[0]
    expect(request).toBeDefined()
    expect(new URL(request!.url).pathname).toBe('/api/auth/private/session')
    expect(request!.credentials).toBe('same-origin')
    expect(request!.headers.get('Content-Type')).toBe('application/json')
    expect(await request!.clone().json()).toEqual({
      secret: 'temporary-test-secret',
    })
    expect(request!.url.includes('temporary-test-secret')).toBe(false)
  })

  it('does not clear private-session CSRF after X reauthorization expires', async () => {
    const { auth, requests } = createTestAuthApi((request) => {
      const path = new URL(request.url).pathname
      if (path === '/api/auth/session')
        return response({ authenticated: true, csrf_token: 'active-csrf' })
      if (path === '/api/auth/x/refresh')
        return response({ error: { code: 'x_reauthorization_required' } }, 401)
      if (path === '/api/auth/logout') return response(null, 204)
      throw new Error(`Unexpected request: ${path}`)
    })

    await auth.readSession()
    await expect(auth.refreshXConnection()).rejects.toMatchObject({
      code: 'x_reauthorization_required',
    })
    await auth.logout()

    expect(requests[2]?.headers.get('X-CSRF-Token')).toBe('active-csrf')
  })

  it('starts X authorization with a fixed same-origin return path', () => {
    expect(getXAuthorizationUrl()).toBe(
      '/api/auth/x/authorize?return_to=%2Fconnections',
    )
    expect(getXAuthorizationUrl().startsWith('https://')).toBe(false)
  })

  it('surfaces rate limiting without retrying or dropping session CSRF', async () => {
    const { auth, requests } = createTestAuthApi((request) => {
      const path = new URL(request.url).pathname
      if (path === '/api/auth/session')
        return response({ authenticated: true, csrf_token: 'active-csrf' })
      if (path === '/api/auth/x/refresh')
        return new Response(
          JSON.stringify({ error: { code: 'rate_limited' } }),
          {
            status: 429,
            headers: {
              'Content-Type': 'application/json',
              'Retry-After': '30',
            },
          },
        )
      if (path === '/api/auth/logout') return response(null, 204)
      throw new Error(`Unexpected request: ${path}`)
    })

    await auth.readSession()
    const refresh = auth.refreshXConnection()
    await expect(refresh).rejects.toBeInstanceOf(ApiResponseError)
    await expect(refresh).rejects.toMatchObject({
      status: 429,
      code: 'rate_limited',
    })
    await auth.logout()

    expect(
      requests.filter(
        (request) => new URL(request.url).pathname === '/api/auth/x/refresh',
      ).length,
    ).toBe(1)
    expect(requests[2]?.headers.get('X-CSRF-Token')).toBe('active-csrf')
  })

  it('preserves the session CSRF token after disconnect failure', async () => {
    const { auth, requests } = createTestAuthApi((request) => {
      const path = new URL(request.url).pathname
      if (path === '/api/auth/session')
        return response({ authenticated: true, csrf_token: 'active-csrf' })
      if (path === '/api/auth/x/disconnect')
        return response({ error: { code: 'connection_unavailable' } }, 503)
      if (path === '/api/auth/logout') return response(null, 204)
      throw new Error(`Unexpected request: ${path}`)
    })

    await auth.readSession()
    await expect(auth.disconnectXConnection()).rejects.toMatchObject({
      status: 503,
      code: 'connection_unavailable',
    })
    await auth.logout()

    expect(requests[1]?.headers.get('X-CSRF-Token')).toBe('active-csrf')
    expect(requests[1]?.credentials).toBe('same-origin')
  })
})

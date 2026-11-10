import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { ApiResponseError, authApi, getXAuthorizationUrl } from './client.ts'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

test('session and connection calls use same-origin cookies and in-memory CSRF', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  globalThis.fetch = (async (input, init) => {
    const url = String(input)
    calls.push({ url, init })
    if (url === '/api/auth/session')
      return Response.json({ authenticated: true, csrf_token: 'csrf-test' })
    if (url === '/api/auth/x/refresh')
      return Response.json({
        connected: true,
        state: 'connected',
        scopes: ['tweet.read'],
        expires_at: null,
      })
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch

  await authApi.readSession()
  await authApi.refreshXConnection()

  assert.deepEqual(
    calls.map(({ url }) => url),
    ['/api/auth/session', '/api/auth/x/refresh'],
  )
  assert.equal(calls[0]?.init?.credentials, 'same-origin')
  assert.equal(calls[1]?.init?.credentials, 'same-origin')
  assert.equal(
    new Headers(calls[1]?.init?.headers).get('X-CSRF-Token'),
    'csrf-test',
  )
  assert.equal(calls[1]?.init?.body, '{}')
})

test('private session sends the secret in the request body only', async () => {
  let observed: { url: string; init?: RequestInit } | undefined
  globalThis.fetch = (async (input, init) => {
    observed = { url: String(input), init }
    return Response.json({ authenticated: true, csrf_token: 'new-csrf' })
  }) as typeof fetch

  await authApi.createPrivateSession('temporary-test-secret')

  assert.equal(observed?.url, '/api/auth/private/session')
  assert.equal(observed?.init?.credentials, 'same-origin')
  assert.equal(
    new Headers(observed?.init?.headers).get('Content-Type'),
    'application/json',
  )
  assert.deepEqual(JSON.parse(String(observed?.init?.body)), {
    secret: 'temporary-test-secret',
  })
  assert.equal(observed?.url.includes('temporary-test-secret'), false)
})

test('X reauthorization expiry does not clear the private-session CSRF token', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  globalThis.fetch = (async (input, init) => {
    const url = String(input)
    calls.push({ url, init })
    if (url === '/api/auth/session')
      return Response.json({ authenticated: true, csrf_token: 'active-csrf' })
    if (url === '/api/auth/x/refresh')
      return Response.json(
        { error: { code: 'x_reauthorization_required' } },
        { status: 401 },
      )
    if (url === '/api/auth/logout') return new Response(null, { status: 204 })
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch

  await authApi.readSession()
  await assert.rejects(authApi.refreshXConnection(), (error: unknown) => {
    assert.ok(error instanceof ApiResponseError)
    assert.equal(error.code, 'x_reauthorization_required')
    return true
  })
  await authApi.logout()

  assert.equal(
    new Headers(calls[2]?.init?.headers).get('X-CSRF-Token'),
    'active-csrf',
  )
})

test('X authorization starts with a fixed same-origin return path', () => {
  assert.equal(
    getXAuthorizationUrl(),
    '/api/auth/x/authorize?return_to=%2Fconnections',
  )
  assert.equal(getXAuthorizationUrl().startsWith('https://'), false)
})

test('rate-limited refresh is surfaced without retrying or dropping the session CSRF token', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  globalThis.fetch = (async (input, init) => {
    const url = String(input)
    calls.push({ url, init })
    if (url === '/api/auth/session')
      return Response.json({ authenticated: true, csrf_token: 'active-csrf' })
    if (url === '/api/auth/x/refresh')
      return Response.json({ error: { code: 'rate_limited' } }, { status: 429 })
    if (url === '/api/auth/logout') return new Response(null, { status: 204 })
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch

  await authApi.readSession()
  await assert.rejects(authApi.refreshXConnection(), (error: unknown) => {
    assert.ok(error instanceof ApiResponseError)
    assert.equal(error.status, 429)
    assert.equal(error.code, 'rate_limited')
    return true
  })
  await authApi.logout()

  assert.equal(
    calls.filter(({ url }) => url === '/api/auth/x/refresh').length,
    1,
  )
  assert.equal(
    new Headers(calls[2]?.init?.headers).get('X-CSRF-Token'),
    'active-csrf',
  )
})

test('disconnect failures preserve the reported connection state and CSRF token', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  globalThis.fetch = (async (input, init) => {
    const url = String(input)
    calls.push({ url, init })
    if (url === '/api/auth/session')
      return Response.json({ authenticated: true, csrf_token: 'active-csrf' })
    if (url === '/api/auth/x/disconnect')
      return Response.json(
        { error: { code: 'connection_unavailable' } },
        { status: 503 },
      )
    if (url === '/api/auth/logout') return new Response(null, { status: 204 })
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch

  await authApi.readSession()
  await assert.rejects(authApi.disconnectXConnection(), (error: unknown) => {
    assert.ok(error instanceof ApiResponseError)
    assert.equal(error.status, 503)
    assert.equal(error.code, 'connection_unavailable')
    return true
  })
  await authApi.logout()

  assert.equal(
    new Headers(calls[1]?.init?.headers).get('X-CSRF-Token'),
    'active-csrf',
  )
  assert.equal(calls[1]?.init?.credentials, 'same-origin')
})

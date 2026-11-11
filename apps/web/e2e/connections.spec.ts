import { expect, test, type Page } from '@playwright/test'

const paths = {
  health: '**/api/health',
  session: '**/api/auth/session',
  connection: '**/api/auth/x/connection',
  refresh: '**/api/auth/x/refresh',
  disconnect: '**/api/auth/x/disconnect',
  authorize: '**/api/auth/x/authorize?*',
}

async function mockSession(
  page: Page,
  result: 'authenticated' | 'unauthenticated' | 'unavailable' = 'authenticated',
) {
  await page.route(paths.health, (route) =>
    route.fulfill({ json: { status: 'ok' } }),
  )
  await page.route(paths.session, (route) => {
    if (result === 'unavailable')
      return route.fulfill({
        status: 503,
        json: { error: { code: 'unavailable' } },
      })
    if (result === 'unauthenticated')
      return route.fulfill({
        status: 401,
        json: { error: { code: 'authentication_required' } },
      })
    return route.fulfill({
      json: { authenticated: true, csrf_token: 'fixture-csrf-token' },
    })
  })
  if (result === 'authenticated') {
    await page.route(paths.connection, (route) =>
      route.fulfill({
        json: {
          connected: false,
          state: null,
          scopes: [],
          expires_at: null,
        },
      }),
    )
  }
}

async function openConnections(page: Page) {
  await page.route('**/api/v1/creators/me/history/imports', (route) =>
    route.fulfill({ json: { items: [], truncated: false } }),
  )
  await page.goto('/connections')
  await expect(
    page.getByRole('heading', { name: 'Welcome to BipMe' }),
  ).toBeVisible()
}

async function goToSourceStep(page: Page) {
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
}

test('renders without horizontal overflow at requested viewport widths', async ({
  page,
}) => {
  await mockSession(page)
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await openConnections(page)
    const dimensions = await page.evaluate(() => ({
      client: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
    }))
    expect(
      dimensions.scroll,
      `horizontal overflow at ${width}px`,
    ).toBeLessThanOrEqual(dimensions.client)
  }
})

test('visits all six onboarding steps and supports back and continue', async ({
  page,
}) => {
  const importRequests: string[] = []
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      request.url().includes('/api/v1/creators/me/history/imports')
    )
      importRequests.push(request.url())
  })
  await mockSession(page)
  await openConnections(page)
  const titles = [
    'Welcome to BipMe',
    'What are you creating toward?',
    'Choose a data source',
    'Review data permissions',
    'Prepare your content history',
    'Your first report will start here',
  ]
  for (const title of titles) {
    await expect(page.getByRole('heading', { name: title })).toBeVisible()
    if (title !== titles.at(-1))
      await page.getByRole('button', { name: 'Continue' }).click()
  }
  await page.getByRole('button', { name: 'Back' }).click()
  await expect(page.getByRole('heading', { name: titles[4] })).toBeVisible()
  await expect(page.getByText('No import has been started')).toBeVisible()
  await expect(
    page.getByText(/Starting or resuming provider work is unavailable/),
  ).toBeVisible()
  await expect(page.getByLabel('Development fixture (synthetic)')).toHaveCount(
    0,
  )
  await expect(page.getByRole('progressbar')).toHaveCount(0)
  expect(importRequests).toHaveLength(0)
})

test('provides labelled goal and niche inputs and labels prototype-only choices', async ({
  page,
}) => {
  await mockSession(page)
  await openConnections(page)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByLabel('Choose your main goal')).toBeVisible()
  await expect(page.getByLabel('Primary niche')).toBeVisible()
  await expect(page.getByLabel('Intended audience')).toBeVisible()
  await expect(page.getByText(/Prototype only/)).toBeVisible()
})

test('shows unauthenticated and unavailable session states', async ({
  page,
}) => {
  await mockSession(page, 'unauthenticated')
  await page.goto('/connections')
  await expect(
    page.getByRole('heading', { name: 'Sign in to your BipMe workspace' }),
  ).toBeVisible()
  await expect(page.getByLabel('Private-session secret')).toBeVisible()

  await page.unrouteAll()
  await mockSession(page, 'unavailable')
  await page.goto('/connections')
  await expect(
    page.getByRole('heading', { name: 'Sign-in status unavailable' }),
  ).toBeVisible()
})

test('opens and closes mobile navigation with focus containment and restoration', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockSession(page)
  await openConnections(page)
  const trigger = page.getByRole('button', { name: 'Open navigation' })
  await trigger.focus()
  await page.keyboard.press('Enter')
  const drawer = page.getByRole('dialog', { name: 'Mobile navigation' })
  await expect(drawer).toBeVisible()
  const close = page.getByRole('button', { name: 'Close navigation' }).first()
  await expect(close).toBeFocused()
  const first = page.getByRole('link', { name: 'BipMe dashboard' })
  await first.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(
    page.getByRole('link', { name: 'Post Monitoring' }),
  ).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(first).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(drawer).toHaveCount(0)
  await expect(trigger).toBeFocused()

  await trigger.click()
  await page.getByRole('button', { name: 'Close navigation' }).first().click()
  await expect(trigger).toBeFocused()
})

test('initiates OAuth through a top-level server navigation with same-origin return path', async ({
  page,
}) => {
  await mockSession(page)
  await openConnections(page)
  await goToSourceStep(page)
  const authorizationRequest = page.waitForRequest((request) =>
    request.url().includes('/api/auth/x/authorize?'),
  )
  await page.getByRole('link', { name: 'Connect X' }).click()
  const request = await authorizationRequest
  expect(request.isNavigationRequest()).toBe(true)
  expect(new URL(request.url()).searchParams.get('return_to')).toBe(
    '/connections',
  )
})

test('shows server connection failures without claiming success', async ({
  page,
}) => {
  await page.route(paths.health, (route) =>
    route.fulfill({ json: { status: 'ok' } }),
  )
  await page.route(paths.session, (route) =>
    route.fulfill({
      json: { authenticated: true, csrf_token: 'fixture-csrf-token' },
    }),
  )
  await page.route(paths.connection, (route) =>
    route.fulfill({ status: 503, json: { error: { code: 'unavailable' } } }),
  )
  await openConnections(page)
  await goToSourceStep(page)
  await expect(page.getByText('Connection status unavailable')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Connect X' })).toBeVisible()
  await expect(page.getByText('Connected', { exact: true })).toHaveCount(0)
})

test('keeps private-session expiry separate from a server-reported expired X token', async ({
  page,
}) => {
  await page.route(paths.health, (route) =>
    route.fulfill({ json: { status: 'ok' } }),
  )
  await page.route(paths.session, (route) =>
    route.fulfill({
      json: { authenticated: true, csrf_token: 'fixture-csrf-token' },
    }),
  )
  await page.route(paths.connection, (route) =>
    route.fulfill({
      json: {
        connected: true,
        state: 'connected',
        scopes: ['tweet.read'],
        expires_at: '2000-01-01T00:00:00Z',
      },
    }),
  )
  await openConnections(page)
  await goToSourceStep(page)
  await expect(page.getByText('X access token expired')).toBeVisible()
  await expect(page.getByText('Private session active')).toBeVisible()
})

test('reports rate limited refresh and failed disconnect without automatic retry', async ({
  page,
}) => {
  let refreshCount = 0
  await page.route(paths.health, (route) =>
    route.fulfill({ json: { status: 'ok' } }),
  )
  await page.route(paths.session, (route) =>
    route.fulfill({
      json: { authenticated: true, csrf_token: 'fixture-csrf-token' },
    }),
  )
  await page.route(paths.connection, (route) =>
    route.fulfill({
      json: {
        connected: true,
        state: 'connected',
        scopes: [],
        expires_at: null,
      },
    }),
  )
  await page.route(paths.refresh, (route) => {
    refreshCount += 1
    return route.fulfill({
      status: 429,
      headers: { 'Retry-After': '60' },
      json: { error: { code: 'rate_limited' } },
    })
  })
  await page.route(paths.disconnect, (route) =>
    route.fulfill({ status: 503, json: { error: { code: 'unavailable' } } }),
  )
  await openConnections(page)
  await goToSourceStep(page)
  await page.getByRole('button', { name: 'Refresh authorization' }).click()
  await expect(page.getByText(/rate limiting requests/)).toBeVisible()
  await expect.poll(() => refreshCount).toBe(1)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Disconnect X' }).click()
  await expect(
    page.getByText(/connection settings were not changed/),
  ).toBeVisible()
  await expect(page.getByText('Connected', { exact: true })).toBeVisible()
})

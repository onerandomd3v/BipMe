import { expect, test, type Page, type Route } from '@playwright/test'
import {
  draftAnalysisFixture,
  draftAssessmentFixture,
  evidenceFixture,
  healthFixture,
  historyImportFixture,
  historyPostsFixture,
  latestReportFixture,
  monitoringFixture,
  permissionFixture,
  postmortemFixture,
  profileFixture,
  publicationLinkFixture,
  sessionFixture,
} from '../src/api/fixtures'

const assessmentId = draftAssessmentFixture.assessment_id

type MockOptions = {
  authenticated?: boolean
  importPage?: typeof historyImportFixture
  publicationLinked?: boolean
  monitoring?: typeof monitoringFixture
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installApiMocks(page: Page, options: MockOptions = {}) {
  const {
    authenticated = true,
    importPage = historyImportFixture,
    publicationLinked = false,
    monitoring = monitoringFixture,
  } = options

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())

    if (url.origin !== 'http://127.0.0.1:4173') {
      await route.abort('blockedbyclient')
      return
    }

    if (!url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }

    const method = route.request().method()
    const path = url.pathname
    if (path === '/api/health') return json(route, healthFixture)
    if (path === '/api/auth/session') {
      return json(
        route,
        authenticated
          ? sessionFixture
          : { authenticated: false, csrf_token: '' },
      )
    }
    if (!authenticated) {
      return json(
        route,
        {
          error: {
            code: 'authentication_required',
            message: 'Sign in required.',
          },
        },
        401,
      )
    }
    if (path === '/api/v1/creators/me/profile')
      return json(route, profileFixture)
    if (path === '/api/v1/creators/me/data-permissions')
      return json(route, permissionFixture)
    if (path === '/api/v1/creators/me/report/latest')
      return json(route, latestReportFixture)
    if (path === '/api/v1/creators/me/report' && method === 'POST')
      return json(route, latestReportFixture.latest_report, 201)
    if (path === '/api/v1/creators/me/history/imports')
      return json(route, importPage)
    if (path === '/api/v1/creators/me/history/posts')
      return json(route, historyPostsFixture)
    if (path === '/api/v1/creators/me/history/evidence')
      return json(route, evidenceFixture)
    if (path === '/api/v1/creators/me/baseline')
      return json(route, {
        ...(await import('../src/api/fixtures')).baselineFixture,
      })
    if (path === '/api/v1/creators/me/draft-assessments' && method === 'POST')
      return json(route, draftAnalysisFixture, 201)
    if (path === `/api/v1/creators/me/draft-assessments/${assessmentId}`)
      return json(route, draftAssessmentFixture)
    if (
      path ===
      '/api/v1/creators/me/draft-assessments/00000000-0000-0000-0000-000000000360'
    )
      return json(route, draftAnalysisFixture)
    if (path.endsWith('/publication') && method === 'GET') {
      return publicationLinked
        ? json(route, publicationLinkFixture)
        : json(
            route,
            {
              error: {
                code: 'publication_not_linked',
                message: 'No publication is linked.',
              },
            },
            404,
          )
    }
    if (path.endsWith('/publication') && method === 'POST')
      return json(route, publicationLinkFixture, 201)
    if (path.endsWith('/postmortem')) return json(route, postmortemFixture)
    if (path.endsWith('/monitoring')) return json(route, monitoring)
    return json(
      route,
      {
        error: {
          code: 'unexpected_test_request',
          message: `Unhandled ${method} ${path}`,
        },
      },
      500,
    )
  })
}

test('denies private workspace access when the session is unauthenticated', async ({
  page,
}) => {
  await installApiMocks(page, { authenticated: false })
  await page.goto('/content-history')
  await expect(
    page.getByText('Sign-in required', { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByText('No private BipMe session is active in this browser.'),
  ).toBeVisible()
})

test('keeps source connection UI gated until COD-357 is integrated', async ({
  page,
}) => {
  await installApiMocks(page)
  await page.goto('/connections')
  await expect(
    page.getByRole('heading', { name: 'This view is not available yet' }),
  ).toBeVisible()
})

test('loads the authenticated report-first dashboard and reaches draft analysis', async ({
  page,
}) => {
  await installApiMocks(page)
  await page.goto('/')
  await expect(page.getByText('Private session active')).toBeVisible()
  await expect(
    page.getByRole('heading', {
      name: 'A grounded view of what you can learn next',
    }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Analyze a Draft' }).click()
  await expect(
    page.getByRole('heading', { name: 'Find a grounded next experiment' }),
  ).toBeVisible()
  await page
    .getByLabel('Draft text')
    .fill('A question-led product lesson for early-stage teams.')
  await page.getByRole('button', { name: 'Analyze this draft' }).click()
  await expect(
    page.getByRole('heading', {
      name: 'What the evidence suggests trying next',
    }),
  ).toBeVisible()
  await expect(
    page.getByText('Moderate evidence', { exact: true }),
  ).toBeVisible()
})

test('renders partial history import and missing evidence without inventing values', async ({
  page,
}) => {
  await installApiMocks(page, {
    importPage: {
      ...historyImportFixture,
      items: [
        {
          ...historyImportFixture.items[0],
          status: 'partial',
          imported_posts: 1,
          next_page_available: true,
        },
      ],
    },
  })
  await page.goto('/content-history')
  await expect(
    page.getByRole('heading', { name: 'Your Content History' }),
  ).toBeVisible()
  await expect(
    page.getByText('Partial import', { exact: true }).first(),
  ).toBeVisible()
  await expect(page.getByText('No observations were returned.')).toBeVisible()
  await expect(page.getByText('No value')).not.toBeVisible()
})

test('attaches a publication and renders monitoring lifecycle plus postmortem boundaries', async ({
  page,
}) => {
  await installApiMocks(page)
  await page.goto(`/post-monitoring?assessment_id=${assessmentId}`)
  await expect(
    page.getByRole('heading', { name: 'Original Distribution Outlook' }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Observation windows' }),
  ).toBeVisible()
  await expect(
    page.getByText('Scheduled: Not scheduled', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText('No receipt was scheduled for this window.'),
  ).toBeVisible()
  await expect(page.getByText('budget blocked')).toBeVisible()
  await page
    .getByLabel('X post URL or numeric post ID')
    .fill('https://x.com/example/status/1900000000000000001')
  await page.getByRole('button', { name: 'Verify and attach post' }).click()
  await expect(page.getByText('Linked post:')).toBeVisible()
  await expect(
    page.getByText('Linked post: 1900000000000000001', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Postmortem and observations' }),
  ).toBeVisible()
  await expect(
    page.getByText('No eligible postmortem result was returned'),
  ).toBeVisible()
})

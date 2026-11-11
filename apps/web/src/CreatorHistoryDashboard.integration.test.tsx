import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { CreatorHistoryDashboard } from './CreatorHistoryDashboard'
import { createApiClient } from './api/client'
import { historyPostsFixture } from './api/fixtures'
import { apiHandlers } from './api/mocks'

const server = setupServer(...apiHandlers)

beforeAll(() => server.listen())
afterAll(() => server.close())
afterEach(() => server.resetHandlers())

describe('CreatorHistoryDashboard with the generated API client', () => {
  it('renders imported counts, exact baseline identity and disclosed evidence', async () => {
    render(<CreatorHistoryDashboard client={createApiClient()} />)

    expect(
      await screen.findByText('Evidence you are permitted to inspect'),
    ).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(
      await screen.findByText('likes · mature_cumulative:mature'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('A disclosed synthetic history post.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Content disclosed')).toBeInTheDocument()
    expect(
      screen.getByText('No observations were returned.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Only one eligible observation supports this baseline.'),
    ).toBeInTheDocument()
  })

  it.each([
    'permission_required',
    'source_policy_blocked',
    'not_known_at_cutoff',
    'future_unknown_disclosure',
  ] as const)(
    'does not render sensitive fields for %s disclosure',
    async (disclosure) => {
      server.use(
        http.get('*/api/v1/creators/me/history/posts', () =>
          HttpResponse.json({
            ...historyPostsFixture,
            items: [
              {
                ...historyPostsFixture.items[0],
                disclosure,
                text: 'SECRET_RESTRICTED_TEXT',
                source_url: 'https://secret.example/restricted',
                observations: [
                  {
                    ...historyPostsFixture.items[0].observations[0],
                    metric_value: '777777',
                  },
                ],
              },
            ],
          }),
        ),
      )
      render(<CreatorHistoryDashboard client={createApiClient()} />)
      expect(
        await screen.findByText(
          disclosure === 'future_unknown_disclosure'
            ? 'Content unavailable'
            : disclosure.replaceAll('_', ' '),
        ),
      ).toBeInTheDocument()
      expect(
        screen.queryByText('SECRET_RESTRICTED_TEXT'),
      ).not.toBeInTheDocument()
      if (disclosure === 'not_known_at_cutoff') {
        expect(screen.getByText('777777')).toBeInTheDocument()
      } else {
        expect(screen.queryByText('777777')).not.toBeInTheDocument()
      }
      expect(
        screen.queryByRole('link', { name: 'Open disclosed source post' }),
      ).not.toBeInTheDocument()
      expect(
        screen.getByText(
          'Post content is unavailable under the current disclosure state.',
        ),
      ).toBeInTheDocument()
    },
  )

  it.each([
    ['https://x.com/i/status/1900000000000000001', true],
    ['https://twitter.com/i/status/1900000000000000001', true],
    ['http://x.com/i/status/1900000000000000001', false],
    ['https://x.com.evil.example/i/status/1900000000000000001', false],
    ['https://x.com@evil.example/i/status/1900000000000000001', false],
    ['javascript:alert(1)', false],
    ['https://x.com/i/status/not-a-post-id', false],
    ['https://x.com/i/status/1900000000000000001?redirect=1', false],
  ] as const)(
    'renders only allowlisted source URLs: %s',
    async (sourceUrl, allowed) => {
      server.use(
        http.get('*/api/v1/creators/me/history/posts', () =>
          HttpResponse.json({
            ...historyPostsFixture,
            items: [
              {
                ...historyPostsFixture.items[0],
                source_url: sourceUrl,
              },
            ],
          }),
        ),
      )
      render(<CreatorHistoryDashboard client={createApiClient()} />)
      expect(
        await screen.findByText('A disclosed synthetic history post.'),
      ).toBeInTheDocument()
      const link = screen.queryByRole('link', {
        name: 'Open disclosed source post',
      })
      if (allowed) expect(link).toHaveAttribute('href', sourceUrl)
      else expect(link).not.toBeInTheDocument()
    },
  )

  it('fails closed for malformed disclosure and metadata fields', async () => {
    server.use(
      http.get('*/api/v1/creators/me/history/posts', () =>
        HttpResponse.json({
          ...historyPostsFixture,
          items: [
            {
              ...historyPostsFixture.items[0],
              disclosure: { unexpected: 'permitted' },
              source: { unexpected: 'authorized_x_api' },
              freshness: { unexpected: 'recorded' },
              published_at: 'not-a-timestamp',
              source_observed_at: { unexpected: 'secret timestamp' },
              text: 'SECRET_RESTRICTED_TEXT',
              source_url: 'https://x.com/i/status/1900000000000000001',
              observations: [
                {
                  ...historyPostsFixture.items[0].observations[0],
                  observed_at: { unexpected: 'secret timestamp' },
                  observed_age_seconds: { unexpected: 1 },
                  source: { unexpected: 'authorized_x_api' },
                },
              ],
            },
          ],
        }),
      ),
    )
    render(<CreatorHistoryDashboard client={createApiClient()} />)
    expect(
      await screen.findByText(
        'Post content is unavailable under the current disclosure state.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('SECRET_RESTRICTED_TEXT')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Open disclosed source post' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Snapshot freshness: unknown')).toBeInTheDocument()
    expect(
      screen.getByText('No observations were returned.'),
    ).toBeInTheDocument()
  })
})

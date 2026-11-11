import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiRequestError, type ApiClient } from './api/client'
import {
  baselineFixture,
  historyImportFixture,
  historyPostsFixture,
} from './api/fixtures'
import { CreatorHistoryDashboard } from './CreatorHistoryDashboard'
import { SYNTHETIC_DEMO_LABEL } from './syntheticDemo'

function fakeClient(
  overrides: Partial<
    Record<'historyImports' | 'historyPosts' | 'baseline', unknown>
  > = {},
) {
  return {
    historyImports: vi.fn().mockResolvedValue(historyImportFixture),
    historyPosts: vi.fn().mockResolvedValue(historyPostsFixture),
    baseline: vi.fn().mockResolvedValue(baselineFixture),
    ...overrides,
  } as unknown as ApiClient
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

describe('CreatorHistoryDashboard states', () => {
  it('does not invent a baseline when no observed series exists', async () => {
    const page = {
      ...historyPostsFixture,
      items: historyPostsFixture.items.map((post) => ({
        ...post,
        observations: post.observations.map((observation) => ({
          ...observation,
          metric_value: null,
          state: 'missing' as const,
        })),
      })),
    }
    const client = fakeClient({
      historyPosts: vi.fn().mockResolvedValue(page),
    })
    render(<CreatorHistoryDashboard client={client} />)
    expect(
      await screen.findByText(/No eligible series is available/),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/public_likes_v1/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Missing/).length).toBeGreaterThan(0)
    expect(client.baseline).not.toHaveBeenCalled()
  })

  it('loads another bounded page through the returned cursor', async () => {
    const secondPage = {
      ...historyPostsFixture,
      next_cursor: null,
      items: [historyPostsFixture.items[0]],
    }
    const historyPosts = vi
      .fn()
      .mockResolvedValueOnce({
        ...historyPostsFixture,
        next_cursor: 'cursor-1',
      })
      .mockResolvedValueOnce(secondPage)
    const client = fakeClient({ historyPosts })
    render(<CreatorHistoryDashboard client={client} />)
    expect(
      await screen.findByRole('button', { name: 'Load more history' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load more history' }))
    await waitFor(() =>
      expect(historyPosts).toHaveBeenCalledWith(
        { limit: 20, cursor: 'cursor-1' },
        expect.any(AbortSignal),
      ),
    )
    expect(screen.getByText('2 loaded')).toBeInTheDocument()
  })

  it('surfaces rate limits and expires an authenticated session on 401', async () => {
    const onSessionExpired = vi.fn()
    const client = fakeClient({
      historyImports: vi.fn().mockRejectedValue(
        new ApiRequestError({
          status: 429,
          code: 'rate_limited',
          message: 'Too many requests',
        }),
      ),
    })
    render(
      <CreatorHistoryDashboard
        client={client}
        onSessionExpired={onSessionExpired}
      />,
    )
    expect(
      await screen.findByText('History requests are rate-limited'),
    ).toBeInTheDocument()

    const unauthorized = fakeClient({
      historyImports: vi.fn().mockRejectedValue(
        new ApiRequestError({
          status: 401,
          code: 'authentication_required',
          message: 'Sign in',
        }),
      ),
    })
    render(
      <CreatorHistoryDashboard
        client={unauthorized}
        onSessionExpired={onSessionExpired}
      />,
    )
    await waitFor(() => expect(onSessionExpired).toHaveBeenCalled())
  })

  it('labels partial imports and keeps empty history explicit', async () => {
    const client = fakeClient({
      historyImports: vi.fn().mockResolvedValue({
        items: [
          {
            ...historyImportFixture.items[0],
            status: 'partial' as const,
            imported_posts: 0,
          },
        ],
        truncated: false,
      }),
      historyPosts: vi.fn().mockResolvedValue({
        ...historyPostsFixture,
        items: [],
      }),
    })
    render(<CreatorHistoryDashboard client={client} />)
    expect(
      (await screen.findAllByText('Partial import')).length,
    ).toBeGreaterThan(0)
    expect(
      screen.getByText(
        'No permitted history posts are available at this cutoff.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/No eligible series is available/),
    ).toBeInTheDocument()
  })

  it('accepts backend synthetic provenance and labels the history view', async () => {
    const client = fakeClient({
      historyImports: vi.fn().mockResolvedValue({
        ...historyImportFixture,
        items: historyImportFixture.items.map((item) => ({
          ...item,
          source: 'synthetic_demo' as const,
        })),
      }),
      historyPosts: vi.fn().mockResolvedValue({
        ...historyPostsFixture,
        items: historyPostsFixture.items.map((post) => ({
          ...post,
          source: 'synthetic_demo' as const,
          observations: post.observations.map((observation) => ({
            ...observation,
            source: 'synthetic_demo' as const,
            provenance: {
              ...observation.provenance,
              source: 'synthetic_demo' as const,
            },
          })),
        })),
      }),
    })
    render(<CreatorHistoryDashboard client={client} />)
    expect(await screen.findByText(SYNTHETIC_DEMO_LABEL)).toBeInTheDocument()
  })

  it('selects among exact metric identities and queries the selected series', async () => {
    const secondMetric = {
      ...historyPostsFixture.items[0].observations[0],
      id: '00000000-0000-0000-0000-000000000395',
      metric_name: 'likes',
      metric_definition: 'public_likes_v2',
      metric_unit: 'count',
      metric_value: '3',
      window_kind: 'age_aligned' as const,
      window_key: '24h',
    }
    const client = fakeClient({
      historyPosts: vi.fn().mockResolvedValue({
        ...historyPostsFixture,
        items: [
          {
            ...historyPostsFixture.items[0],
            observations: [
              historyPostsFixture.items[0].observations[0],
              secondMetric,
            ],
          },
        ],
      }),
    })
    render(<CreatorHistoryDashboard client={client} />)
    const selector = await screen.findByLabelText(
      'Metric series discovered in loaded history',
    )
    await waitFor(() =>
      expect(client.baseline).toHaveBeenCalledWith(
        expect.objectContaining({
          metric: 'likes',
          definition: 'public_likes_v1',
          unit: 'likes',
          window_kind: 'mature_cumulative',
          window_key: 'mature',
        }),
        expect.any(AbortSignal),
      ),
    )
    fireEvent.change(selector, {
      target: {
        value: JSON.stringify([
          'likes',
          'public_likes_v2',
          'count',
          'age_aligned',
          '24h',
        ]),
      },
    })
    await waitFor(() =>
      expect(client.baseline).toHaveBeenLastCalledWith(
        expect.objectContaining({
          metric: 'likes',
          definition: 'public_likes_v2',
          unit: 'count',
          window_kind: 'age_aligned',
          window_key: '24h',
        }),
        expect.any(AbortSignal),
      ),
    )
  })

  it('keeps delimiter-containing metric identities independently selectable', async () => {
    const firstMetric = {
      ...historyPostsFixture.items[0].observations[0],
      id: '00000000-0000-0000-0000-000000000397',
      metric_name: 'likes|public',
      metric_definition: 'v1',
    }
    const secondMetric = {
      ...historyPostsFixture.items[0].observations[0],
      id: '00000000-0000-0000-0000-000000000398',
      metric_name: 'likes',
      metric_definition: 'public|v1',
    }
    const client = fakeClient({
      historyPosts: vi.fn().mockResolvedValue({
        ...historyPostsFixture,
        items: [
          {
            ...historyPostsFixture.items[0],
            observations: [firstMetric, secondMetric],
          },
        ],
      }),
    })
    render(<CreatorHistoryDashboard client={client} />)
    const selector = await screen.findByLabelText(
      'Metric series discovered in loaded history',
    )
    expect(screen.getAllByRole('option')).toHaveLength(2)
    fireEvent.change(selector, {
      target: {
        value: JSON.stringify([
          'likes',
          'public|v1',
          'likes',
          'mature_cumulative',
          'mature',
        ]),
      },
    })
    await waitFor(() =>
      expect(client.baseline).toHaveBeenCalledWith(
        expect.objectContaining({
          metric: 'likes',
          definition: 'public|v1',
          unit: 'likes',
          window_kind: 'mature_cumulative',
          window_key: 'mature',
        }),
        expect.any(AbortSignal),
      ),
    )
  })

  it('keeps history visible when baseline fails and retries only baseline', async () => {
    const baseline = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiRequestError({
          status: 422,
          code: 'validation_error',
          message: 'Unsupported',
        }),
      )
      .mockResolvedValueOnce(baselineFixture)
    const client = fakeClient({ baseline })
    render(<CreatorHistoryDashboard client={client} />)
    expect(
      await screen.findByText('A disclosed synthetic history post.'),
    ).toBeInTheDocument()
    expect(
      await screen.findByText('This metric series cannot be analyzed'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry baseline' }))
    await waitFor(() =>
      expect(
        screen.getByText(
          'Only one eligible observation supports this baseline.',
        ),
      ).toBeInTheDocument(),
    )
    expect(client.historyPosts).toHaveBeenCalledTimes(1)
    expect(client.historyImports).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['observed', 'Unknown / unavailable'],
    ['invalid', 'Invalid value'],
  ] as const)(
    'renders %s nullable metric state safely',
    async (state, label) => {
      const page = {
        ...historyPostsFixture,
        items: [
          {
            ...historyPostsFixture.items[0],
            observations: [
              {
                ...historyPostsFixture.items[0].observations[0],
                metric_value: null,
                state,
              },
            ],
          },
        ],
      }
      const client = fakeClient({
        historyPosts: vi.fn().mockResolvedValue(page),
      })
      render(<CreatorHistoryDashboard client={client} />)
      expect(await screen.findByText(label)).toBeInTheDocument()
    },
  )

  it.each([
    ['0', '0'],
    ['12.50', '12.50'],
    ['-3.25', '-3.25'],
    [null, 'Unknown / unavailable'],
    [{ value: 4 }, 'Unknown / unavailable'],
    [[4], 'Unknown / unavailable'],
    [true, 'Unknown / unavailable'],
    ['not-a-number', 'Unknown / unavailable'],
    [undefined, 'Unknown / unavailable'],
  ] as const)('guards runtime metric value %p', async (metricValue, label) => {
    const page = {
      ...historyPostsFixture,
      items: [
        {
          ...historyPostsFixture.items[0],
          observations: [
            {
              ...historyPostsFixture.items[0].observations[0],
              metric_value: metricValue,
              state: 'observed' as const,
            },
          ],
        },
      ],
    }
    const client = fakeClient({
      historyPosts: vi.fn().mockResolvedValue(page),
    })
    render(<CreatorHistoryDashboard client={client} />)
    expect(await screen.findByText(label)).toBeInTheDocument()
  })

  it.each([429, 503] as const)(
    'keeps history visible for baseline %s',
    async (status) => {
      const client = fakeClient({
        baseline: vi.fn().mockRejectedValue(
          new ApiRequestError({
            status,
            code: `http_${status}`,
            message: 'Unavailable',
          }),
        ),
      })
      render(<CreatorHistoryDashboard client={client} />)
      expect(
        await screen.findByText('A disclosed synthetic history post.'),
      ).toBeInTheDocument()
      expect(await screen.findByRole('alert')).toBeInTheDocument()
    },
  )

  it('ignores a stale baseline response after the selected series changes', async () => {
    const first = deferred<typeof baselineFixture>()
    const second = deferred<typeof baselineFixture>()
    const secondObservation = {
      ...historyPostsFixture.items[0].observations[0],
      id: '00000000-0000-0000-0000-000000000396',
      metric_name: 'likes',
      metric_definition: 'public_likes_v2',
      metric_unit: 'count',
      window_kind: 'age_aligned' as const,
      window_key: '24h',
    }
    const historyPosts = vi.fn().mockResolvedValue({
      ...historyPostsFixture,
      items: [
        {
          ...historyPostsFixture.items[0],
          observations: [
            historyPostsFixture.items[0].observations[0],
            secondObservation,
          ],
        },
      ],
    })
    const baseline = vi.fn((query: { definition?: string }) =>
      query.definition === 'public_likes_v2' ? second.promise : first.promise,
    )
    const client = fakeClient({ historyPosts, baseline })
    render(<CreatorHistoryDashboard client={client} />)
    const selector = await screen.findByLabelText(
      'Metric series discovered in loaded history',
    )
    await waitFor(() => expect(baseline).toHaveBeenCalledTimes(1))
    fireEvent.change(selector, {
      target: {
        value: JSON.stringify([
          'likes',
          'public_likes_v2',
          'count',
          'age_aligned',
          '24h',
        ]),
      },
    })
    await waitFor(() =>
      expect(baseline).toHaveBeenLastCalledWith(
        expect.objectContaining({ definition: 'public_likes_v2' }),
        expect.any(AbortSignal),
      ),
    )
    second.resolve({
      ...baselineFixture,
      metric: {
        ...baselineFixture.metric,
        definition: 'public_likes_v2',
        unit: 'count',
        window_kind: 'age_aligned',
        window_key: '24h',
      },
    } as unknown as typeof baselineFixture)
    expect(
      await screen.findByRole('heading', {
        name: /likes · age_aligned:24h/,
      }),
    ).toBeInTheDocument()
    first.resolve(baselineFixture)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(
      screen.getByRole('heading', {
        name: /likes · age_aligned:24h/,
      }),
    ).toBeInTheDocument()
  })

  it.each([
    ['metric', 'reposts'],
    ['definition', 'public_reposts_v1'],
    ['unit', 'count'],
    ['window_kind', 'age_aligned'],
    ['window_key', '24h'],
  ] as const)(
    'rejects a baseline response with a mismatched %s identity field',
    async (field, value) => {
      const client = fakeClient({
        baseline: vi.fn().mockResolvedValue({
          ...baselineFixture,
          metric: {
            ...baselineFixture.metric,
            [field]: value,
          },
        }),
      })
      render(<CreatorHistoryDashboard client={client} />)
      expect(
        await screen.findByText('A disclosed synthetic history post.'),
      ).toBeInTheDocument()
      expect(
        await screen.findByText(
          'The baseline response did not match the selected metric series.',
        ),
      ).toBeInTheDocument()
      expect(
        screen.queryByText(
          'Only one eligible observation supports this baseline.',
        ),
      ).not.toBeInTheDocument()
    },
  )

  it('keeps history visible for a malformed baseline response', async () => {
    const client = fakeClient({
      baseline: vi.fn().mockResolvedValue({
        ...baselineFixture,
        evidence_strength: { unexpected: 'High' },
        statistics: { unexpected: 12 },
      } as unknown),
    })
    render(<CreatorHistoryDashboard client={client} />)
    expect(
      await screen.findByText('A disclosed synthetic history post.'),
    ).toBeInTheDocument()
    expect(
      await screen.findByText(
        'The baseline response was unavailable in a safe format.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('P50')).not.toBeInTheDocument()
  })

  it('renders exclusions and null statistics without crashing', async () => {
    const client = fakeClient({
      baseline: vi.fn().mockResolvedValue({
        ...baselineFixture,
        evidence_strength: 'Insufficient',
        eligible_post_count: 0,
        effective_sample_size: 0,
        statistics: null,
        exclusions: {
          not_returned: 2,
          permission_required: 1,
        },
        limitations: [],
      }),
    })
    render(<CreatorHistoryDashboard client={client} />)
    expect(await screen.findByText('not_returned: 2')).toBeInTheDocument()
    expect(screen.getByText('permission_required: 1')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Insufficient eligible observations support percentile statistics.',
      ),
    ).toBeInTheDocument()
  })

  it('does not clear the session for a rights-denial 403', async () => {
    const onSessionExpired = vi.fn()
    const client = fakeClient({
      baseline: vi.fn().mockRejectedValue(
        new ApiRequestError({
          status: 403,
          code: 'x_account_not_allowed',
          message: 'Not permitted',
        }),
      ),
    })
    render(
      <CreatorHistoryDashboard
        client={client}
        onSessionExpired={onSessionExpired}
      />,
    )
    expect(await screen.findByText('Not permitted')).toBeInTheDocument()
    expect(onSessionExpired).not.toHaveBeenCalled()
  })
})

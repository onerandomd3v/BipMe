import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from '../api/client'
import { ConnectionsPage } from './ConnectionsPage'

const mocks = vi.hoisted(() => ({
  historyImports: vi.fn(),
  readXConnection: vi.fn(),
}))

vi.mock('../api/client', async () => {
  const actual =
    await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    apiClient: { ...actual.apiClient, historyImports: mocks.historyImports },
  }
})

vi.mock('../auth/client', async () => {
  const actual =
    await vi.importActual<typeof import('../auth/client')>('../auth/client')
  return {
    ...actual,
    authApi: { ...actual.authApi, readXConnection: mocks.readXConnection },
  }
})

const importStatus = (
  status: 'running' | 'partial' | 'complete' | 'unavailable',
) => ({
  import_id: 'cod-357-import-fixture',
  status,
  requested_posts: 20,
  imported_posts: status === 'running' ? 8 : status === 'unavailable' ? 0 : 12,
  pages_read: 1,
  next_page_available: status === 'running' || status === 'partial',
  source: 'authorized_x_api' as const,
  started_at: '2026-11-11T10:00:00Z',
  completed_at: status === 'running' ? null : '2026-11-11T10:01:00Z',
})

async function openImportStep() {
  render(
    <ConnectionsPage sessionStatus="authenticated" onSessionStatus={vi.fn()} />,
  )
  for (let index = 0; index < 4; index += 1)
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
}

describe('Connections import status', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.readXConnection.mockResolvedValue({
      connected: false,
      state: null,
      scopes: [],
      expires_at: null,
    })
    mocks.historyImports.mockResolvedValue({ items: [], truncated: false })
  })

  it.each([
    ['running', 'Import in progress'],
    ['partial', 'Partial import'],
    ['complete', 'Import completed'],
    ['unavailable', 'Import unavailable'],
  ] as const)(
    'shows the server-reported %s import state',
    async (status, title) => {
      mocks.historyImports.mockResolvedValueOnce({
        items: [importStatus(status)],
        truncated: false,
      })
      await openImportStep()
      expect(await screen.findByText(title)).toBeInTheDocument()
      expect(
        screen.getByText(
          new RegExp(
            `server reports ${status === 'running' ? 8 : status === 'unavailable' ? 0 : 12} of 20 requested posts imported`,
            'i',
          ),
        ),
      ).toBeInTheDocument()
      expect(mocks.historyImports).toHaveBeenCalledWith(
        20,
        expect.any(AbortSignal),
      )
    },
  )

  it('shows an empty state when the server has no imports and manual refresh reads status only', async () => {
    await openImportStep()
    expect(await screen.findByText('No import has been started')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }))
    await waitFor(() => expect(mocks.historyImports).toHaveBeenCalledTimes(2))
    expect(mocks.historyImports.mock.calls[1]?.[0]).toBe(20)
  })

  it('shows rate limiting without automatic retry and allows a manual status check', async () => {
    mocks.historyImports.mockRejectedValueOnce(
      new ApiRequestError({
        status: 429,
        code: 'rate_limited',
        message: 'Rate limited',
      }),
    )
    await openImportStep()
    await waitFor(() => expect(mocks.historyImports).toHaveBeenCalledTimes(1))
    expect(
      await screen.findByText('Import status rate limited'),
    ).toBeInTheDocument()
    expect(mocks.historyImports).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }))
    expect(await screen.findByText('No import has been started')).toBeVisible()
    expect(mocks.historyImports).toHaveBeenCalledTimes(2)
  })

  it('aborts a stale import-status read when leaving the import step', async () => {
    mocks.historyImports.mockImplementationOnce(
      (_limit: number, signal: AbortSignal) =>
        new Promise((resolve) => {
          signal.addEventListener(
            'abort',
            () => resolve({ items: [], truncated: false }),
            { once: true },
          )
        }),
    )
    await openImportStep()
    const signal = mocks.historyImports.mock.calls[0]?.[1] as AbortSignal
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await waitFor(() => expect(signal.aborted).toBe(true))
  })
})

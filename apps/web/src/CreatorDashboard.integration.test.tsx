import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { CreatorDashboard } from './CreatorDashboard'
import { createApiClient } from './api/client'
import { apiHandlers } from './api/mocks'

const server = setupServer(...apiHandlers)

beforeAll(() => server.listen())
afterAll(() => server.close())

describe('CreatorDashboard with the shared API client', () => {
  it('loads synthetic COD-378 responses through MSW and hands off report context', async () => {
    const onAnalyzeDraft = vi.fn()
    render(
      <CreatorDashboard
        client={createApiClient()}
        onAnalyzeDraft={onAnalyzeDraft}
      />,
    )

    expect(
      await screen.findByText('Creator Intelligence Report'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze a Draft' }))
    expect(onAnalyzeDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        reportId: '00000000-0000-0000-0000-000000000380',
        coverage: 'personal_only_partial',
      }),
    )
  })

  it('uses the shared client for deletion and reloads the report state', async () => {
    render(
      <CreatorDashboard
        client={createApiClient()}
        onAnalyzeDraft={() => undefined}
      />,
    )
    await screen.findByRole('button', { name: 'Delete report snapshots' })
    fireEvent.click(
      screen.getByRole('button', { name: 'Delete report snapshots' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Delete snapshots' }))
    await waitFor(() =>
      expect(
        screen.getByText('Report snapshots deleted successfully.'),
      ).toBeInTheDocument(),
    )
  })
})

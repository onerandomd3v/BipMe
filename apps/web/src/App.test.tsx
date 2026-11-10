import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { healthFixture } from './api/fixtures'

const api = vi.hoisted(() => ({
  health: vi.fn(),
  session: vi.fn(),
  subscribeSessionInvalidation: vi.fn(),
  invalidate: null as (() => void) | null,
}))

vi.mock('./CreatorDashboard', () => ({
  CreatorDashboard: ({
    onAnalyzeDraft,
  }: {
    onAnalyzeDraft: (context: { reportId: string }) => void
  }) => (
    <button
      type="button"
      onClick={() => onAnalyzeDraft({ reportId: 'test-report-id' })}
    >
      Analyze current report
    </button>
  ),
}))

vi.mock('./api/client', async () => {
  const actual =
    await vi.importActual<typeof import('./api/client')>('./api/client')
  return { ...actual, apiClient: api }
})

describe('App session boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.health.mockResolvedValue(healthFixture)
    api.session.mockResolvedValue({ authenticated: true, csrf_token: 'csrf' })
    api.subscribeSessionInvalidation.mockImplementation(
      (listener: () => void) => {
        api.invalidate = listener
        return () => undefined
      },
    )
  })

  it('clears draft context when the authenticated session is invalidated', async () => {
    window.history.replaceState(null, '', '/')
    render(<App />)
    fireEvent.click(
      await screen.findByRole('button', { name: 'Analyze current report' }),
    )
    expect(
      await screen.findByText(/Draft analysis context is available/),
    ).toBeInTheDocument()
    expect(screen.getByText(/test-report-id/)).toBeInTheDocument()

    api.invalidate?.()
    await waitFor(() =>
      expect(screen.getByText('Sign-in required')).toBeInTheDocument(),
    )
    expect(screen.queryByText(/test-report-id/)).not.toBeInTheDocument()
  })
})

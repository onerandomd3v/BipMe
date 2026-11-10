import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import {
  healthFixture,
  latestReportFixture,
  permissionFixture,
  profileFixture,
} from './api/fixtures'

const api = vi.hoisted(() => ({
  health: vi.fn(),
  session: vi.fn(),
  subscribeSessionInvalidation: vi.fn(),
  profile: vi.fn(),
  dataPermissions: vi.fn(),
  latestReport: vi.fn(),
  saveProfile: vi.fn(),
  saveDataPermissions: vi.fn(),
  generateReport: vi.fn(),
  deleteReports: vi.fn(),
  invalidate: null as (() => void) | null,
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
    api.profile.mockResolvedValue(profileFixture)
    api.dataPermissions.mockResolvedValue(permissionFixture)
    api.latestReport.mockResolvedValue(latestReportFixture)
  })

  it('clears draft context when the authenticated session is invalidated', async () => {
    window.history.replaceState(null, '', '/')
    render(<App />)
    expect(
      await screen.findByText('Creator Intelligence Report'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze a Draft' }))
    expect(
      await screen.findByText(/Draft analysis context is available/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(new RegExp(latestReportFixture.latest_report!.id)),
    ).toBeInTheDocument()

    api.invalidate?.()
    await waitFor(() =>
      expect(screen.getByText('Sign-in required')).toBeInTheDocument(),
    )
    expect(
      screen.queryByText(new RegExp(latestReportFixture.latest_report!.id)),
    ).not.toBeInTheDocument()
  })
})

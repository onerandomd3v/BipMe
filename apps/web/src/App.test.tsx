import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import {
  healthFixture,
  latestReportFixture,
  permissionFixture,
  profileFixture,
  baselineFixture,
  historyImportFixture,
  historyPostsFixture,
} from './api/fixtures'

const api = vi.hoisted(() => ({
  health: vi.fn(),
  session: vi.fn(),
  subscribeSessionInvalidation: vi.fn(),
  profile: vi.fn(),
  dataPermissions: vi.fn(),
  latestReport: vi.fn(),
  historyImports: vi.fn(),
  historyPosts: vi.fn(),
  baseline: vi.fn(),
  saveProfile: vi.fn(),
  saveDataPermissions: vi.fn(),
  generateReport: vi.fn(),
  deleteReports: vi.fn(),
  createDraftAssessment: vi.fn(),
  draftAssessment: vi.fn(),
  historyEvidence: vi.fn(),
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
    api.historyImports.mockResolvedValue(historyImportFixture)
    api.historyPosts.mockResolvedValue(historyPostsFixture)
    api.baseline.mockResolvedValue(baselineFixture)
  })

  it('clears draft context when the authenticated session is invalidated', async () => {
    window.history.replaceState(null, '', '/')
    render(<App />)
    expect(
      await screen.findByText('Creator Intelligence Report'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze a Draft' }))
    expect(
      await screen.findByText('Find a grounded next experiment'),
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

  it('does not resurrect a report handoff after leaving and returning to draft analysis', async () => {
    window.history.replaceState(null, '', '/')
    render(<App />)
    await screen.findByText('Creator Intelligence Report')
    fireEvent.click(screen.getByRole('button', { name: 'Analyze a Draft' }))
    expect(await screen.findByText(/Using report context/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }))
    await screen.findByText('Creator Intelligence Report')
    fireEvent.click(screen.getByRole('link', { name: 'Analyze a Draft' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cannot submit')
    expect(screen.queryByText(/Using report context/)).not.toBeInTheDocument()
  it('renders the authenticated history route through the App boundary', async () => {
    window.history.replaceState(null, '', '/content-history')
    render(<App />)
    expect(
      await screen.findByText('Evidence you are permitted to inspect'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('combobox', {
        name: 'Metric series discovered in loaded history',
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Development · Authenticated API preview'),
    ).toBeInTheDocument()
  })
})

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CreatorDashboard } from './CreatorDashboard'
import { ApiRequestError } from './api/client'
import {
  latestReportFixture,
  permissionFixture,
  profileFixture,
  reportFixture,
} from './api/fixtures'

const api = vi.hoisted(() => ({
  profile: vi.fn(),
  dataPermissions: vi.fn(),
  latestReport: vi.fn(),
  saveProfile: vi.fn(),
  saveDataPermissions: vi.fn(),
  generateReport: vi.fn(),
  deleteReports: vi.fn(),
}))

vi.mock('./api/client', async () => {
  const actual =
    await vi.importActual<typeof import('./api/client')>('./api/client')
  return { ...actual, apiClient: api }
})

function configureReport() {
  api.profile.mockResolvedValue(profileFixture)
  api.dataPermissions.mockResolvedValue(permissionFixture)
  api.latestReport.mockResolvedValue(latestReportFixture)
}

describe('CreatorDashboard rendered states', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    configureReport()
  })

  it('renders a maximum of three deduplicated suggestions and hands off typed context', async () => {
    api.latestReport.mockResolvedValue({
      ...latestReportFixture,
      latest_report: {
        ...reportFixture,
        report: {
          ...reportFixture.report,
          experiments: [
            { hypothesis: 'Try a concise opening', evidence_ids: ['e1'] },
            { hypothesis: 'Try a concise opening', evidence_ids: ['e2'] },
            { hypothesis: 'Ask one clear question', evidence_ids: ['e3'] },
          ],
          opportunities: [
            { summary: 'Add a clear next action', evidence_ids: ['e4'] },
            { summary: 'A fourth item', evidence_ids: ['e5'] },
          ],
        },
      },
    })
    const onAnalyzeDraft = vi.fn()
    render(<CreatorDashboard onAnalyzeDraft={onAnalyzeDraft} />)
    expect(await screen.findByText('Try a concise opening')).toBeInTheDocument()
    expect(screen.getByText('Ask one clear question')).toBeInTheDocument()
    expect(screen.getByText('Add a clear next action')).toBeInTheDocument()
    expect(screen.queryByText('A fourth item')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze a Draft' }))
    expect(onAnalyzeDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        reportId: reportFixture.id,
        creatorKey: reportFixture.creator_key,
        goalsRevision: reportFixture.goals_revision,
      }),
    )
  })

  it('requires accessible confirmation and supports cancellation before deletion', async () => {
    render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    await screen.findByText('Delete report snapshots')
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Delete report snapshots' })[0],
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    expect(screen.getByRole('alertdialog')).toHaveTextContent(
      'Underlying imported source records are retained',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete report snapshots' }),
      ).toHaveFocus(),
    )
    expect(api.deleteReports).not.toHaveBeenCalled()
  })

  it('cancels the deletion dialog with Escape and contains Tab focus', async () => {
    render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    await screen.findByText('Delete report snapshots')
    fireEvent.click(
      screen.getByRole('button', { name: 'Delete report snapshots' }),
    )
    const cancel = screen.getByRole('button', { name: 'Cancel' })
    const confirm = screen.getByRole('button', { name: 'Delete snapshots' })
    await waitFor(() => expect(cancel).toHaveFocus())
    confirm.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(cancel).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(confirm).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete report snapshots' }),
      ).toHaveFocus(),
    )
  })

  it('shows field-level validation feedback during onboarding', async () => {
    api.profile.mockResolvedValue({ status: 'not_configured', profile: null })
    api.latestReport.mockResolvedValue({
      status: 'awaiting_profile',
      latest_report: null,
    })
    api.saveProfile.mockRejectedValue(
      new ApiRequestError({
        code: 'validation_error',
        message: 'Request validation failed.',
        details: [{ loc: ['body', 'niche'], msg: 'Niche is too short.' }],
        status: 422,
      }),
    )
    render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    const input = await screen.findByLabelText('Niche or area of work')
    fireEvent.input(input, { target: { value: 'AI' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Build my report' }))
    await waitFor(() =>
      expect(screen.getByText('Niche is too short.')).toBeInTheDocument(),
    )
  })

  it('renders the empty import state and lets the creator change consent', async () => {
    api.latestReport.mockResolvedValue({
      status: 'awaiting_import',
      latest_report: null,
    })
    render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    expect(
      await screen.findByText('Your report is waiting for permitted history'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Analyze a Draft' }),
    ).toBeDisabled()
    expect(
      screen.getByText(
        'Draft analysis becomes available after a report snapshot is ready.',
      ),
    ).toBeInTheDocument()

    api.profile.mockResolvedValue({ status: 'not_configured', profile: null })
    api.latestReport.mockResolvedValue({
      status: 'awaiting_profile',
      latest_report: null,
    })
    const { unmount } = render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    expect(await screen.findByLabelText(/Allow processing/)).toBeChecked()
    fireEvent.click(screen.getByLabelText(/Allow processing/))
    expect(screen.getByLabelText(/Allow processing/)).not.toBeChecked()
    unmount()
  })

  it.each([
    [401, 'Sign-in required'],
    [429, 'rate-limited'],
  ])('renders a safe state for HTTP %s failures', async (status, text) => {
    api.profile.mockRejectedValue(
      new ApiRequestError({
        code: status === 401 ? 'authentication_required' : 'rate_limited',
        message: 'Request failed',
        status,
      }),
    )
    render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    expect(await screen.findByText(text, { exact: false })).toBeInTheDocument()
  })

  it('announces refresh and deletion success and prevents duplicate deletion', async () => {
    api.generateReport.mockResolvedValue(reportFixture)
    api.deleteReports.mockResolvedValue(undefined)
    render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    await screen.findByText('Refresh report')
    fireEvent.click(screen.getByRole('button', { name: 'Refresh report' }))
    expect(
      await screen.findByText('Report refreshed successfully.'),
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Delete report snapshots' }),
    )
    const confirm = screen.getByRole('button', { name: 'Delete snapshots' })
    fireEvent.click(confirm)
    fireEvent.click(confirm)
    await waitFor(() => expect(api.deleteReports).toHaveBeenCalledTimes(1))
    expect(
      await screen.findByText('Report snapshots deleted successfully.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Report snapshots deleted successfully.'),
    ).toHaveTextContent('Report snapshots deleted successfully.')
  })

  it('announces refresh and deletion failures without duplicate refreshes', async () => {
    api.generateReport.mockRejectedValue(
      new ApiRequestError({
        code: 'report_generation_unavailable',
        message: 'Report generation is temporarily unavailable.',
        status: 503,
      }),
    )
    api.deleteReports.mockRejectedValue(
      new ApiRequestError({
        code: 'report_deletion_unavailable',
        message: 'Report deletion is temporarily unavailable.',
        status: 503,
      }),
    )
    render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    await screen.findByText('Refresh report')
    const refresh = screen.getByRole('button', { name: 'Refresh report' })
    fireEvent.click(refresh)
    fireEvent.click(refresh)
    await waitFor(() => expect(api.generateReport).toHaveBeenCalledTimes(1))
    expect(
      await screen.findByText('Report generation is temporarily unavailable.'),
    ).toBeInTheDocument()

    fireEvent.click(
      screen.getByRole('button', { name: 'Delete report snapshots' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Delete snapshots' }))
    expect(
      await screen.findByText('Report deletion is temporarily unavailable.'),
    ).toBeInTheDocument()
  })

  it('does not update the UI after an onboarding request resolves post-unmount', async () => {
    const pending = {
      resolve: null as
        ((profile: typeof profileFixture.profile) => void) | null,
    }
    api.saveProfile.mockReturnValue(
      new Promise((resolve) => {
        pending.resolve = resolve
      }),
    )
    api.profile.mockResolvedValue({ status: 'not_configured', profile: null })
    api.latestReport.mockResolvedValue({
      status: 'awaiting_profile',
      latest_report: null,
    })
    const { unmount } = render(<CreatorDashboard onAnalyzeDraft={vi.fn()} />)
    await screen.findByRole('button', { name: 'Build my report' })
    fireEvent.submit(screen.getByRole('button', { name: 'Build my report' }))
    unmount()
    pending.resolve?.(profileFixture.profile)
    await Promise.resolve()
    expect(document.querySelector('.onboarding-card')).not.toBeInTheDocument()
  })
})

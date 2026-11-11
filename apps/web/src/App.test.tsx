import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { ApiRequestError } from './api/client'
import {
  draftAssessmentFixture,
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
  privateSession: vi.fn(),
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
  publication: vi.fn(),
  linkPublication: vi.fn(),
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
    api.draftAssessment.mockResolvedValue({
      accepted_hypothesis: null,
      assessed_at: '2026-11-10T12:00:00Z',
      assessment_id: '00000000-0000-4000-8000-000000000365',
      assumptions: [],
      comparable_evidence: [],
      decision_state: 'insufficient_evidence',
      exclusions: [],
      input_fingerprint: 'sha256:app-fixture',
      limitations: [],
      metrics: [],
      observations: [],
      retrieval_candidate_count: 0,
      retrieval_coverage_limitations: [],
      retrieval_eligible_count: 0,
      retrieval_excluded_count: 0,
      retrieval_exclusions: [],
      retrieval_state: 'no_match',
      retrieval_truncated: false,
      retrieval_vector_candidate_count: 0,
      suggested_hypothesis: null,
      versions: {
        baseline: 'baseline-v1',
        decision: 'decision-v1',
        decision_config: 'decision-config-v1',
        embedding_identity: 'embedding-fixture',
        profile: 'profile-v1',
        ranking_config: 'ranking-config-v1',
        retrieval: 'retrieval-v1',
      },
    })
    api.publication.mockResolvedValue({
      assessment_id: '00000000-0000-4000-8000-000000000365',
      assessed_at: '2026-11-10T12:00:00Z',
      assessed_fingerprint: 'sha256:app-fixture',
      accepted_hypothesis: null,
      canonical_post_id: '00000000-0000-4000-8000-000000000366',
      external_post_id: '1900000000000000001',
      published_at: '2026-11-10T13:00:00Z',
      version_match_state: 'unknown',
      linkage_state: 'linked',
      linked_at: '2026-11-10T13:01:00Z',
    })
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
      expect(screen.getByText('Welcome back')).toBeInTheDocument(),
    )
    expect(
      screen.queryByText(new RegExp(latestReportFixture.latest_report!.id)),
    ).not.toBeInTheDocument()
  })

  it('uses the server-backed private sign-in without exposing a demo switch', async () => {
    api.session.mockResolvedValue({ authenticated: false, csrf_token: '' })
    api.privateSession.mockResolvedValue({
      authenticated: true,
      csrf_token: 'csrf-after-sign-in',
    })
    window.history.replaceState(null, '', '/')
    render(<App />)
    const secret = await screen.findByLabelText('Private sign-in secret')
    fireEvent.input(secret, {
      target: { value: 'a'.repeat(32) },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(api.privateSession).toHaveBeenCalledWith('a'.repeat(32))
    expect(
      await screen.findByText('Creator Intelligence Report'),
    ).toBeInTheDocument()
    expect(
      screen.queryByLabelText('Private sign-in secret'),
    ).not.toBeInTheDocument()
  })

  it('does not resurrect a report handoff after leaving and returning to draft analysis', async () => {
    window.history.replaceState(null, '', '/')
    render(<App />)
    await screen.findByText('Creator Intelligence Report')
    fireEvent.click(screen.getByRole('button', { name: 'Analyze a Draft' }))
    expect(await screen.findByText(/Using report context/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'Overview' }))
    await screen.findByText('Creator Intelligence Report')
    fireEvent.click(screen.getByRole('link', { name: 'Analyze a Draft' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cannot submit')
    expect(screen.queryByText(/Using report context/)).not.toBeInTheDocument()
  })

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
    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Connections' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText('Development · Authenticated API preview'),
    ).not.toBeInTheDocument()
  })

  it('switches monitoring assessment context across browser history', async () => {
    const assessmentA = '00000000-0000-4000-8000-000000000365'
    const assessmentB = '00000000-0000-4000-8000-000000000367'
    api.draftAssessment.mockImplementation((id: string) =>
      Promise.resolve({ ...draftAssessmentFixture, assessment_id: id }),
    )
    api.publication.mockImplementation((id: string) =>
      Promise.resolve({
        assessment_id: id,
        assessed_at: '2026-11-10T12:00:00Z',
        assessed_fingerprint: 'sha256:app-fixture',
        accepted_hypothesis: null,
        canonical_post_id: '00000000-0000-4000-8000-000000000366',
        external_post_id: '1900000000000000001',
        published_at: '2026-11-10T13:00:00Z',
        version_match_state: 'unknown',
        linkage_state: 'linked',
        linked_at: '2026-11-10T13:01:00Z',
      }),
    )
    window.history.replaceState(
      null,
      '',
      `/post-monitoring?assessment_id=${assessmentA}`,
    )
    render(<App />)
    expect(await screen.findByText(assessmentA)).toBeInTheDocument()

    window.history.pushState(
      null,
      '',
      `/post-monitoring?assessment_id=${assessmentB}`,
    )
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect(await screen.findByText(assessmentB)).toBeInTheDocument()
    expect(screen.queryByText(assessmentA)).not.toBeInTheDocument()

    window.history.pushState(
      null,
      '',
      `/post-monitoring?assessment_id=${assessmentA}`,
    )
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect(await screen.findByText(assessmentA)).toBeInTheDocument()
  })

  it('unmounts monitoring safely when the session expires during attachment', async () => {
    const assessmentId = '00000000-0000-4000-8000-000000000365'
    let resolvePublication: (() => void) | undefined
    api.publication.mockRejectedValue(
      new ApiRequestError({
        status: 404,
        code: 'publication_not_linked',
        message: 'No publication is linked.',
      }),
    )
    api.linkPublication.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolvePublication = resolve
        }),
    )
    window.history.replaceState(
      null,
      '',
      `/post-monitoring?assessment_id=${assessmentId}`,
    )
    render(<App />)
    const input = await screen.findByLabelText('X post URL or numeric post ID')
    fireEvent.input(input, { target: { value: '1900000000000000001' } })
    fireEvent.click(
      screen.getByRole('button', { name: 'Verify and attach post' }),
    )
    api.invalidate?.()
    expect(await screen.findByText('Welcome back')).toBeInTheDocument()
    resolvePublication?.()
    expect(
      screen.queryByText('Original Distribution Outlook'),
    ).not.toBeInTheDocument()
  })
})

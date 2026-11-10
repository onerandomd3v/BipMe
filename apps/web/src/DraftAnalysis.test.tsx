import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError, type ApiClient } from './api/client'
import { draftAnalysisFixture, evidenceFixture } from './api/fixtures'
import { DraftAnalysis } from './DraftAnalysis'

const context = {
  creatorKey: 'creator',
  reportId: 'report',
  goalsRevision: 1,
  reportAsOf: '2026-11-09T12:02:00Z',
  coverage: 'personal_only_partial',
} as const

function clientMock() {
  return {
    createDraftAssessment: vi.fn().mockResolvedValue(draftAnalysisFixture),
    draftAssessment: vi.fn().mockResolvedValue(draftAnalysisFixture),
    historyEvidence: vi.fn().mockResolvedValue(evidenceFixture),
  } as unknown as ApiClient & {
    createDraftAssessment: ReturnType<typeof vi.fn>
    draftAssessment: ReturnType<typeof vi.fn>
    historyEvidence: ReturnType<typeof vi.fn>
  }
}

describe('DraftAnalysis', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('validates empty input without making an API request', async () => {
    const client = clientMock()
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a draft')
    expect(client.createDraftAssessment).not.toHaveBeenCalled()
  })

  it('reuses the idempotency key for a retry and changes it after editing', async () => {
    const client = clientMock()
    client.createDraftAssessment
      .mockRejectedValueOnce(
        new ApiRequestError({
          code: 'temporary',
          message: 'Try again',
          status: 503,
        }),
      )
      .mockResolvedValue(draftAnalysisFixture)
    render(<DraftAnalysis context={context} client={client} />)
    const input = screen.getByLabelText('Draft text')
    fireEvent.change(input, { target: { value: 'A retryable draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByText('What the evidence suggests trying next')
    const firstKey = client.createDraftAssessment.mock.calls[0][1]
    const retryKey = client.createDraftAssessment.mock.calls[1][1]
    expect(retryKey).toBe(firstKey)
    fireEvent.change(input, { target: { value: 'A materially changed draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await waitFor(() =>
      expect(client.createDraftAssessment).toHaveBeenCalledTimes(3),
    )
    expect(client.createDraftAssessment.mock.calls[2][1]).not.toBe(firstKey)
  })

  it('prevents duplicate submission while the request is in flight', async () => {
    const client = clientMock()
    let resolve: (value: typeof draftAnalysisFixture) => void = () => undefined
    client.createDraftAssessment.mockImplementation(
      () =>
        new Promise((nextResolve) => {
          resolve = nextResolve
        }),
    )
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'One submission' },
    })
    const button = screen.getByRole('button', { name: 'Analyze this draft' })
    fireEvent.click(button)
    fireEvent.click(button)
    expect(client.createDraftAssessment).toHaveBeenCalledTimes(1)
    resolve(draftAnalysisFixture)
    await screen.findByText('What the evidence suggests trying next')
  })

  it('keeps the analysis visible when evidence enrichment fails', async () => {
    const client = clientMock()
    client.historyEvidence.mockRejectedValue(
      new ApiRequestError({
        code: 'store_failure',
        message: 'Evidence store unavailable',
        status: 503,
      }),
    )
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Keep the evidence boundary' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(
      await screen.findByText('What the evidence suggests trying next'),
    ).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Comparable post enrichment status',
    )
  })

  it('default-denies restricted content and observations', async () => {
    const client = clientMock()
    client.historyEvidence.mockResolvedValue({
      ...evidenceFixture,
      items: [
        {
          ...evidenceFixture.items[0],
          text: 'PRIVATE SECRET TEXT',
          source_url: 'https://x.com/i/status/9999999999',
          disclosure: 'source_policy_blocked',
          observations: [
            {
              ...evidenceFixture.items[0].observations[0],
              metric_name: 'private_metric_name',
              metric_value: 'private_metric_value',
              observed_at: '2026-11-03T12:00:00Z',
              state: 'missing',
            },
          ],
        },
      ],
    })
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Restricted source test' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(
      await screen.findByText('Source policy blocks disclosure'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText("Which product decision changed your team's week?"),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('PRIVATE SECRET TEXT')).not.toBeInTheDocument()
    expect(screen.queryByText('private_metric_name')).not.toBeInTheDocument()
    expect(screen.queryByText('private_metric_value')).not.toBeInTheDocument()
    expect(screen.queryByText('Open permitted source')).not.toBeInTheDocument()
  })

  it('preserves historical observations but suppresses not-known-at-cutoff source details', async () => {
    const client = clientMock()
    client.historyEvidence.mockResolvedValue({
      ...evidenceFixture,
      items: [
        {
          ...evidenceFixture.items[0],
          text: 'PRIVATE CUTOFF TEXT',
          source_url: null,
          source_observed_at: null,
          disclosure: 'not_known_at_cutoff',
        },
      ],
    })
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Cutoff disclosure test' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(
      await screen.findByText('Not known at assessment cutoff'),
    ).toBeInTheDocument()
    expect(screen.getByText('replies · replies · age:24h')).toBeInTheDocument()
    expect(screen.queryByText('PRIVATE CUTOFF TEXT')).not.toBeInTheDocument()
    expect(
      screen.queryByText('Source: Authorized X API'),
    ).not.toBeInTheDocument()
  })

  it('does not render unsafe permitted source URLs', async () => {
    const client = clientMock()
    client.historyEvidence.mockResolvedValue({
      ...evidenceFixture,
      items: [
        {
          ...evidenceFixture.items[0],
          source_url: 'https://x.com/i/status/1234567890?token=secret',
        },
      ],
    })
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Unsafe URL test' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByText('Permitted source')
    expect(
      screen.queryByRole('link', { name: 'Open permitted source' }),
    ).not.toBeInTheDocument()
  })

  it('keeps valid evidence when an unrelated page item is malformed', async () => {
    const client = clientMock()
    const secondPostId = '00000000-0000-0000-0000-000000000363'
    client.createDraftAssessment.mockResolvedValue({
      ...draftAnalysisFixture,
      comparable_evidence: [
        ...draftAnalysisFixture.comparable_evidence,
        {
          ...draftAnalysisFixture.comparable_evidence[0],
          post_id: secondPostId,
          retrieval_position: 2,
        },
      ],
    })
    client.historyEvidence.mockResolvedValue({
      ...evidenceFixture,
      items: [evidenceFixture.items[0], null],
    })
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Partial evidence test' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(
      await screen.findByText(
        "Which product decision changed your team's week?",
      ),
    ).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '1 of 2 comparable posts were validated',
    )
  })

  it.each([
    [401, 'Your private session is no longer valid'],
    [429, 'Analysis is rate-limited'],
    [503, 'analysis service is temporarily unavailable'],
    [403, 'not permitted for the current creator session'],
    [404, 'saved assessment is not available'],
    [409, 'failure'],
    [422, 'did not match the analysis contract'],
  ])('shows an explicit state for API status %s', async (status, message) => {
    const client = clientMock()
    client.createDraftAssessment.mockRejectedValue(
      new ApiRequestError({ code: 'failure', message: 'failure', status }),
    )
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: `Status ${status}` },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('retrieves a saved assessment by its returned UUID', async () => {
    const client = clientMock()
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Retrieve this assessment' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByRole('button', { name: 'Refresh saved assessment' })
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh saved assessment' }),
    )
    await waitFor(() =>
      expect(client.draftAssessment).toHaveBeenCalledWith(
        draftAnalysisFixture.assessment_id,
        expect.anything(),
      ),
    )
    expect(client.historyEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        assessment_id: draftAnalysisFixture.assessment_id,
      }),
      expect.anything(),
    )
  })

  it('rejects an assessment refresh whose returned ID differs from the requested ID', async () => {
    const client = clientMock()
    client.draftAssessment.mockResolvedValue({
      ...draftAnalysisFixture,
      assessment_id: 'different-assessment-id',
    })
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Assessment identity test' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByRole('button', { name: 'Refresh saved assessment' })
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh saved assessment' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'draft analysis could not be completed',
    )
  })

  it('does not let a late rejected request overwrite a newer submission', async () => {
    const client = clientMock()
    let rejectFirst: (error: Error) => void = () => undefined
    client.createDraftAssessment
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectFirst = reject
          }),
      )
      .mockResolvedValueOnce(draftAnalysisFixture)
    render(<DraftAnalysis context={context} client={client} />)
    const input = screen.getByLabelText('Draft text')
    fireEvent.change(input, { target: { value: 'First request' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    fireEvent.change(input, { target: { value: 'Second request' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByText('What the evidence suggests trying next')
    rejectFirst(new Error('old request failed'))
    await waitFor(() =>
      expect(screen.queryByText('old request failed')).not.toBeInTheDocument(),
    )
  })

  it('invalidates an in-flight assessment when the draft changes', async () => {
    const client = clientMock()
    let resolve: (value: typeof draftAnalysisFixture) => void = () => undefined
    client.createDraftAssessment.mockImplementation(
      () =>
        new Promise((nextResolve) => {
          resolve = nextResolve
        }),
    )
    render(<DraftAnalysis context={context} client={client} />)
    const input = screen.getByLabelText('Draft text')
    fireEvent.change(input, { target: { value: 'Original draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    fireEvent.change(input, { target: { value: 'Edited draft' } })
    resolve(draftAnalysisFixture)
    await waitFor(() =>
      expect(client.createDraftAssessment).toHaveBeenCalledTimes(1),
    )
    expect(
      screen.queryByText('What the evidence suggests trying next'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Analyze this draft' }),
    ).toBeEnabled()
  })

  it('keeps the prior assessment from an older evidence request after editing', async () => {
    const client = clientMock()
    let resolveEvidence: (value: typeof evidenceFixture) => void = () =>
      undefined
    client.historyEvidence.mockImplementation(
      () =>
        new Promise((nextResolve) => {
          resolveEvidence = nextResolve
        }),
    )
    render(<DraftAnalysis context={context} client={client} />)
    const input = screen.getByLabelText('Draft text')
    fireEvent.change(input, { target: { value: 'Evidence draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByText('What the evidence suggests trying next')
    fireEvent.change(input, { target: { value: 'New evidence draft' } })
    resolveEvidence(evidenceFixture)
    await waitFor(() =>
      expect(
        screen.queryByText('Assessment 00000000-0000-0000-0000-000000000360'),
      ).not.toBeInTheDocument(),
    )
    expect(
      screen.queryByText("Which product decision changed your team's week?"),
    ).not.toBeInTheDocument()
  })

  it.each([
    ['metrics', { metrics: [null] }],
    ['limitations', { limitations: [42] }],
    ['observations', { observations: [{ explanation: 7 }] }],
    ['hypothesis', { suggested_hypothesis: { kind: 'bad' } }],
  ])('rejects malformed nested %s responses safely', async (_label, change) => {
    const client = clientMock()
    client.createDraftAssessment.mockResolvedValue({
      ...draftAnalysisFixture,
      ...change,
    } as never)
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Malformed response' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'draft analysis could not be completed',
    )
    expect(
      screen.queryByText('What the evidence suggests trying next'),
    ).not.toBeInTheDocument()
  })

  it.each([
    [
      'wrong assessment',
      { ...evidenceFixture, assessment_id: 'other-assessment' },
    ],
    [
      'unexpected post',
      {
        ...evidenceFixture,
        items: [{ ...evidenceFixture.items[0], id: 'unexpected-post' }],
      },
    ],
    [
      'duplicate post',
      {
        ...evidenceFixture,
        items: [evidenceFixture.items[0], evidenceFixture.items[0]],
      },
    ],
  ])('does not render %s evidence', async (_label, page) => {
    const client = clientMock()
    client.historyEvidence.mockResolvedValue(page)
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Identity boundary' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByText('What the evidence suggests trying next')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Comparable post enrichment status',
    )
    expect(
      screen.queryByText("Which product decision changed your team's week?"),
    ).not.toBeInTheDocument()
  })

  it('renders provenance and grounded sample-quality details', async () => {
    const client = clientMock()
    client.createDraftAssessment.mockResolvedValue({
      ...draftAnalysisFixture,
      exclusions: [
        ['invalid_metric', 2],
        ['not_observed', 1],
      ],
      retrieval_truncated: true,
      metrics: [
        {
          ...draftAnalysisFixture.metrics[0],
          limitations: ['Sparse observation coverage.'],
        },
      ],
    })
    client.historyEvidence.mockResolvedValue({
      ...evidenceFixture,
      items: [{ ...evidenceFixture.items[0], observations_truncated: true }],
    })
    render(<DraftAnalysis context={context} client={client} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Quality details' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(
      await screen.findByText('Source: Authorized X API'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Derived creator-relative summary/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Retrieval candidates:/)).toBeInTheDocument()
    expect(
      screen.getByText(/Assessment exclusions: invalid metric: 2/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Metric limitations: Sparse observation coverage/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Observations truncated/)).toBeInTheDocument()
    expect(
      screen.getByText(/Candidate retrieval was truncated/),
    ).toBeInTheDocument()
  })

  it('renders a safe unconfigured state for direct navigation', () => {
    const back = vi.fn()
    const client = clientMock()
    render(
      <DraftAnalysis context={null} client={client} onBackToDashboard={back} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('cannot submit')
    expect(
      screen.getByRole('button', { name: 'Analyze this draft' }),
    ).toBeDisabled()
    fireEvent.click(
      screen.getByRole('button', { name: 'Back to Creator Intelligence' }),
    )
    expect(back).toHaveBeenCalledOnce()
    expect(client.createDraftAssessment).not.toHaveBeenCalled()
  })
})

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PostMonitoring } from './PostMonitoring'
import { ApiRequestError, type ApiClient } from './api/client'
import type { components } from './api/generated/schema'
import { monitoringFixture } from './api/fixtures'
import { SYNTHETIC_DEMO_LABEL } from './syntheticDemo'

const assessmentId = '00000000-0000-4000-8000-000000000365'

const assessment = {
  accepted_hypothesis: null,
  assessment_id: assessmentId,
  assessed_at: '2026-11-10T12:00:00Z',
  decision_state: 'supported',
  input_fingerprint: 'sha256:assessment-fixture',
  metrics: [],
  comparable_evidence: [],
  observations: [],
  assumptions: [],
  limitations: [],
  retrieval_state: 'matched',
  retrieval_coverage_limitations: [],
  retrieval_candidate_count: 0,
  retrieval_eligible_count: 0,
  retrieval_excluded_count: 0,
  retrieval_exclusions: [],
  retrieval_truncated: false,
  retrieval_vector_candidate_count: 0,
  exclusions: [],
  suggested_hypothesis: null,
  versions: {
    baseline: 'baseline-v1',
    decision: 'decision-v1',
    decision_config: 'decision-config-v1',
    embedding_identity: 'embedding-v1',
    profile: 'profile-v1',
    ranking_config: 'ranking-v1',
    retrieval: 'retrieval-v1',
  },
} as unknown as components['schemas']['DraftAnalysisResponse']

const publication = {
  assessment_id: assessmentId,
  assessed_at: assessment.assessed_at,
  assessed_fingerprint: assessment.input_fingerprint,
  accepted_hypothesis: null,
  canonical_post_id: '00000000-0000-4000-8000-000000000366',
  external_post_id: '1900000000000000001',
  published_at: '2026-11-10T13:00:00Z',
  version_match_state: 'match',
  linkage_state: 'linked',
  linked_at: '2026-11-10T13:01:00Z',
} satisfies components['schemas']['PublicationLinkResponse']

const evaluatedPostmortem = {
  state: 'evaluated',
  assessment_id: assessmentId,
  assessed_at: assessment.assessed_at,
  published_post: {
    availability: 'available',
    canonical_post_id: publication.canonical_post_id,
    external_post_id: publication.external_post_id,
    published_at: publication.published_at,
    version_match_state: 'match',
  },
  original_outlook: assessment,
  postmortem: {
    assessment_id: assessmentId,
    published_post_id: publication.canonical_post_id,
    version: 'postmortem-v1',
    version_state: 'verified',
    limitations: [],
    hypothesis_evaluation: null,
    observed_outcomes: [],
    metric_comparisons: [
      {
        metric: 'likes',
        metric_definition: 'public_likes_v1',
        unit: 'likes',
        window_key: 'age:24h',
        window_kind: 'age_aligned',
        status: 'scored',
        observed_at: '2026-11-11T12:00:00Z',
        observed_value: 12,
        historical_median: 10,
        deviation_from_median: 2,
        relative_percentile: 0.7,
        within_reference_range: true,
        effective_sample_size: 3,
        matched_sample_count: 3,
        comparison_post_ids: [],
        comparison_observations: [],
        reference_range: null,
        limitations: [],
      },
    ],
  },
  limitations: [],
}

function client(overrides: Partial<ApiClient> = {}) {
  return {
    draftAssessment: vi.fn().mockResolvedValue(assessment),
    publication: vi.fn().mockRejectedValue(
      new ApiRequestError({
        status: 404,
        code: 'publication_not_linked',
        message: 'No publication is linked.',
      }),
    ),
    postmortem: vi.fn().mockResolvedValue({
      state: 'publication_pending',
      assessment_id: assessmentId,
      assessed_at: assessment.assessed_at,
      published_post: null,
      original_outlook: assessment,
      postmortem: null,
      limitations: ['No linked publication is available yet.'],
    }),
    monitoring: vi.fn().mockResolvedValue(monitoringFixture),
    linkPublication: vi.fn().mockResolvedValue(publication),
    ...overrides,
  } as unknown as ApiClient
}

describe('PostMonitoring', () => {
  it('renders monitoring lifecycle without inventing unsupplied windows or values', async () => {
    const validMonitoring = {
      ...monitoringFixture,
      original_outlook: assessment,
      published_post: null,
    }
    const fake = client({
      monitoring: vi.fn().mockResolvedValue(validMonitoring),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(await screen.findByText('Observation windows')).toBeInTheDocument()
    expect(screen.getByText('1h')).toBeInTheDocument()
    expect(screen.getByText('Not scheduled')).toBeInTheDocument()
    expect(
      screen.getByText('No receipt was scheduled for this window.'),
    ).toBeInTheDocument()
    const observation = screen.getByText(
      (_, element) =>
        element?.tagName === 'P' &&
        element.textContent?.includes('impressions') === true,
    )
    expect(observation).toHaveTextContent('42')
    expect(observation).toHaveTextContent('86400s')
    expect(screen.queryByText('skipped')).not.toBeInTheDocument()
  })

  it('accepts and labels backend synthetic monitoring provenance', async () => {
    const fake = client({
      monitoring: vi.fn().mockResolvedValue({
        ...monitoringFixture,
        original_outlook: assessment,
        limitations: [SYNTHETIC_DEMO_LABEL],
      }),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(
      (await screen.findAllByText(SYNTHETIC_DEMO_LABEL)).length,
    ).toBeGreaterThan(0)
  })

  it('keeps the assessment visible when monitoring is malformed', async () => {
    const validMonitoring = {
      ...monitoringFixture,
      original_outlook: assessment,
      published_post: null,
    }
    const fake = client({
      monitoring: vi.fn().mockResolvedValue({
        ...validMonitoring,
        windows: [
          { ...validMonitoring.windows[0], observations: [{ bad: true }] },
        ],
      }),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(
      await screen.findByText('Original Distribution Outlook'),
    ).toBeInTheDocument()
    expect(
      await screen.findByText('The monitoring response was invalid.'),
    ).toBeInTheDocument()
  })

  it('does not call APIs for a missing or invalid assessment identity', () => {
    const fake = client()
    render(<PostMonitoring assessmentId={null} client={fake} />)
    expect(screen.getByRole('alert')).toHaveTextContent('valid assessment ID')
    expect(fake.draftAssessment).not.toHaveBeenCalled()
  })

  it('loads an immutable assessment, allows one deliberate attach, and preserves unavailable downstream state', async () => {
    const fake = client()
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(
      await screen.findByText('Original Distribution Outlook'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Saved monitoring only.*does not fetch new X data/),
    ).toBeInTheDocument()
    const input = screen.getByLabelText('X post URL or numeric post ID')
    fireEvent.input(input, {
      target: { value: 'https://x.com/example/status/1900000000000000001' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Verify and attach post' }),
    )
    await waitFor(() =>
      expect(fake.linkPublication).toHaveBeenCalledWith(assessmentId, {
        post_url_or_id: 'https://x.com/example/status/1900000000000000001',
      }),
    )
    expect(
      await screen.findByText(/Matches the assessed version/),
    ).toBeInTheDocument()
    expect(screen.getByText(assessmentId)).toBeInTheDocument()
  })

  it.each([
    ['match', 'Matches the assessed version'],
    ['mismatch', 'Does not match the assessed version'],
    ['unknown', 'Could not verify the assessed version'],
  ] as const)(
    'renders publication version state %s distinctly',
    async (state, text) => {
      const fake = client({
        publication: vi.fn().mockResolvedValue({
          ...publication,
          version_match_state: state,
        }),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
      expect(await screen.findByText(new RegExp(text))).toBeInTheDocument()
    },
  )

  it('rejects a publication GET that belongs to another assessment', async () => {
    const fake = client({
      publication: vi.fn().mockResolvedValue({
        ...publication,
        assessment_id: '00000000-0000-4000-8000-000000000367',
      }),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'does not belong to this assessment',
    )
    expect(
      screen.queryByText(publication.external_post_id),
    ).not.toBeInTheDocument()
  })

  it('rejects a publication POST that belongs to another assessment', async () => {
    const fake = client({
      linkPublication: vi.fn().mockResolvedValue({
        ...publication,
        assessment_id: '00000000-0000-4000-8000-000000000367',
      }),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    const input = await screen.findByLabelText('X post URL or numeric post ID')
    fireEvent.input(input, { target: { value: '1900000000000000001' } })
    fireEvent.click(
      screen.getByRole('button', { name: 'Verify and attach post' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'did not match the original assessment',
    )
    expect(
      screen.queryByText(publication.external_post_id),
    ).not.toBeInTheDocument()
  })

  it.each([
    ['assessment UUID', { assessment_id: 'not-a-uuid' }],
    ['canonical post UUID', { canonical_post_id: 'not-a-uuid' }],
    ['external uint64 ID', { external_post_id: '18446744073709551616' }],
    ['assessed timestamp', { assessed_at: 'not-a-date' }],
    ['published timestamp', { published_at: 'not-a-date' }],
    ['linkage enum', { linkage_state: 'pending' }],
    ['version enum', { version_match_state: 'pending' }],
    [
      'nested hypothesis',
      { accepted_hypothesis: { question: 'missing required fields' } },
    ],
  ] as const)(
    'rejects malformed publication %s on GET and POST',
    async (_field, invalidFields) => {
      const getFake = client({
        publication: vi.fn().mockResolvedValue({
          ...publication,
          ...invalidFields,
        }),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={getFake} />)
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'publication response was invalid',
      )
      expect(
        screen.queryByText(publication.external_post_id),
      ).not.toBeInTheDocument()
      expect(getFake.linkPublication).not.toHaveBeenCalled()
      cleanup()

      const postFake = client({
        linkPublication: vi.fn().mockResolvedValue({
          ...publication,
          ...invalidFields,
        }),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={postFake} />)
      const input = await screen.findByLabelText(
        'X post URL or numeric post ID',
      )
      fireEvent.input(input, { target: { value: '1900000000000000001' } })
      fireEvent.click(
        screen
          .getAllByRole('button', { name: 'Verify and attach post' })
          .at(-1)!,
      )
      expect(await screen.findAllByRole('alert')).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            textContent: expect.stringContaining(
              'publication response was invalid',
            ),
          }),
        ]),
      )
      expect(postFake.linkPublication).toHaveBeenCalledTimes(1)
    },
  )

  it('renders a typed evaluated postmortem with actual timestamps and units', async () => {
    const fake = client({
      publication: vi.fn().mockResolvedValue(publication),
      postmortem: vi.fn().mockResolvedValue(evaluatedPostmortem),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(
      await screen.findByText('Postmortem and observations'),
    ).toBeInTheDocument()
    expect(await screen.findByText('12 likes; scored')).toBeInTheDocument()
    expect(screen.getByText(/Measurement:/).parentElement).toHaveTextContent(
      /2026/,
    )
    expect(
      screen.getByText(/Saved monitoring only.*does not fetch new X data/),
    ).toBeInTheDocument()
  })

  it('rejects a postmortem whose immutable original outlook does not match', async () => {
    const fake = client({
      postmortem: vi.fn().mockResolvedValue({
        ...evaluatedPostmortem,
        original_outlook: {
          ...assessment,
          input_fingerprint: 'sha256:wrong-outlook',
        },
      }),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'does not match this assessment',
    )
    expect(
      screen.getByText('Original Distribution Outlook'),
    ).toBeInTheDocument()
  })

  it.each([
    [401, 'authentication_required', 'Authentication failed.'],
    [
      403,
      'published_post_owner_mismatch',
      'not owned by the authorized X account',
    ],
    [
      409,
      'published_post_already_linked',
      'already linked to another assessment',
    ],
    [422, 'publication_before_assessment', 'predates the original assessment'],
    [429, 'rate_limited', 'Verification is rate limited.'],
    [
      503,
      'publication_verification_unavailable',
      'Verification is unavailable.',
    ],
  ] as const)(
    'renders an explicit publication error for %s',
    async (status, code, message) => {
      const fake = client({
        linkPublication: vi
          .fn()
          .mockRejectedValue(new ApiRequestError({ status, code, message })),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
      const input = await screen.findByLabelText(
        'X post URL or numeric post ID',
      )
      fireEvent.input(input, { target: { value: '1900000000000000001' } })
      fireEvent.click(
        screen.getByRole('button', { name: 'Verify and attach post' }),
      )
      expect(await screen.findByRole('alert')).toHaveTextContent(
        status === 403
          ? 'not owned by the authorized X account'
          : status === 409
            ? 'already linked to another assessment'
            : status === 422
              ? 'predates the original assessment'
              : message,
      )
    },
  )

  it.each([
    [401, 'Authentication failed.'],
    [403, 'Rights denied.'],
    [404, 'Publication missing.'],
    [422, 'Publication response was invalid.'],
    [429, 'Rate limited.'],
    [503, 'Service unavailable.'],
  ] as const)(
    'renders a safe state for publication GET %s without triggering POST',
    async (status, message) => {
      const fake = client({
        publication: vi.fn().mockRejectedValue(
          new ApiRequestError({
            status,
            code: `publication_${status}`,
            message,
          }),
        ),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
      expect(await screen.findByRole('alert')).toHaveTextContent(message)
      expect(
        screen.queryByText(publication.external_post_id),
      ).not.toBeInTheDocument()
      expect(fake.linkPublication).not.toHaveBeenCalled()
    },
  )

  it('renders safe states for publication GET network and malformed-response failures', async () => {
    const failures = [
      new ApiRequestError({
        status: null,
        code: 'network_error',
        message: 'The API could not be reached.',
      }),
      new ApiRequestError({
        status: 200,
        code: 'malformed_response',
        message: 'The publication response was invalid.',
      }),
    ]
    for (const failure of failures) {
      cleanup()
      const fake = client({
        publication: vi.fn().mockRejectedValue(failure),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
      expect(await screen.findByRole('alert')).toHaveTextContent(
        failure.message,
      )
      expect(fake.linkPublication).not.toHaveBeenCalled()
    }
  })

  it('shows the verification-cost and read-only warning before submit without calling POST', async () => {
    const fake = client()
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(
      await screen.findByText(
        /Viewing the existing publication status does not call X/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/potentially billable official X verification/),
    ).toBeInTheDocument()
    expect(fake.linkPublication).not.toHaveBeenCalled()
  })

  it('renders the original assessment evidence without treating missing ranges as zero', async () => {
    const outlookAssessment = {
      ...assessment,
      input_fingerprint: 'sha256:outlook-fixture',
      retrieval_state: 'matched',
      retrieval_candidate_count: 3,
      retrieval_eligible_count: 2,
      metrics: [
        {
          metric: 'replies',
          metric_definition: 'public_reply_count_v1',
          window: 'age:24h',
          evidence_strength: 'Moderate',
          effective_sample_size: 2,
          eligible_post_count: 2,
          coverage: 1,
          exclusion_counts: [],
          supporting_post_ids: [],
          limitations: ['Small sample.'],
          outlook: null,
          statistics: null,
        },
      ],
      comparable_evidence: [
        {
          post_id: '00000000-0000-4000-8000-000000000390',
          relevance: 0.91,
          inclusion_reasons: ['Same metric window.'],
          components: {
            semantic: 0.9,
            format: null,
            intent: null,
            structure: 0.8,
            topic: 0.9,
          },
          retrieval_position: 1,
        },
      ],
      observations: [
        {
          kind: 'coverage_limitation',
          explanation: 'Only two eligible posts support the comparison.',
          evidence_strength: 'Moderate',
          metric: 'replies',
          metric_definition: 'public_reply_count_v1',
          window: 'age:24h',
          supporting_post_ids: [],
          limitations: ['Do not infer causality.'],
          evidence_statistics: null,
        },
      ],
      assumptions: ['Synthetic evidence only.'],
      limitations: ['Historical range unavailable.'],
      retrieval_coverage_limitations: ['Coverage is partial.'],
    } as unknown as components['schemas']['DraftAnalysisResponse']
    const fake = client({
      draftAssessment: vi.fn().mockResolvedValue(outlookAssessment),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(
      await screen.findByText('Evidence and limitations'),
    ).toBeInTheDocument()
    expect(screen.getByText('sha256:outlook-fixture')).toBeInTheDocument()
    expect(screen.getByText('replies')).toBeInTheDocument()
    expect(
      screen.getByText(
        /Historical range unavailable; no value was substituted/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Only two eligible posts support the comparison/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Same metric window/)).toBeInTheDocument()
  })

  it('rejects non-canonical references before any provider-backed request', async () => {
    const fake = client()
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    const input = await screen.findByLabelText('X post URL or numeric post ID')
    fireEvent.input(input, {
      target: { value: 'http://x.com/user/status/123' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Verify and attach post' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'canonical HTTPS',
    )
    expect(fake.linkPublication).not.toHaveBeenCalled()
  })

  it('accepts the maximum uint64 post ID and rejects the next value', async () => {
    const validFake = client()
    render(<PostMonitoring assessmentId={assessmentId} client={validFake} />)
    const validInput = await screen.findByLabelText(
      'X post URL or numeric post ID',
    )
    fireEvent.input(validInput, {
      target: { value: '18446744073709551615' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Verify and attach post' }),
    )
    expect(validFake.linkPublication).toHaveBeenCalledTimes(1)
    expect(
      await screen.findByText(/Matches the assessed version/),
    ).toBeInTheDocument()

    const invalidFake = client()
    render(<PostMonitoring assessmentId={assessmentId} client={invalidFake} />)
    const invalidInput = await screen.findAllByLabelText(
      'X post URL or numeric post ID',
    )
    fireEvent.input(invalidInput.at(-1)!, {
      target: { value: '18446744073709551616' },
    })
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Verify and attach post' }).at(-1)!,
    )
    expect(await screen.findAllByRole('alert')).toHaveLength(1)
    expect(invalidFake.linkPublication).not.toHaveBeenCalled()
  })

  it('prevents duplicate submits while verification is pending', async () => {
    let resolve: ((value: typeof publication) => void) | undefined
    const fake = client({
      linkPublication: vi.fn().mockImplementation(
        () =>
          new Promise<typeof publication>((done) => {
            resolve = done
          }),
      ),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    const input = await screen.findByLabelText('X post URL or numeric post ID')
    fireEvent.input(input, { target: { value: '1900000000000000001' } })
    const submit = screen.getByRole('button', {
      name: 'Verify and attach post',
    })
    fireEvent.click(submit)
    fireEvent.click(submit)
    expect(fake.linkPublication).toHaveBeenCalledTimes(1)
    resolve?.(publication)
    expect(
      await screen.findByText(/Matches the assessed version/),
    ).toBeInTheDocument()
  })

  it('ignores a late response after the assessment context changes', async () => {
    let resolve:
      | ((value: components['schemas']['DraftAnalysisResponse']) => void)
      | undefined
    const secondId = '00000000-0000-4000-8000-000000000367'
    const fake = client({
      draftAssessment: vi.fn().mockImplementation((id: string) =>
        id === assessmentId
          ? new Promise((done) => {
              resolve = done
            })
          : Promise.resolve({ ...assessment, assessment_id: secondId }),
      ),
    })
    const view = render(
      <PostMonitoring assessmentId={assessmentId} client={fake} />,
    )
    view.rerender(<PostMonitoring assessmentId={secondId} client={fake} />)
    expect(await screen.findByText(secondId)).toBeInTheDocument()
    await act(async () => {
      resolve?.(assessment)
    })
    expect(screen.getByText(secondId)).toBeInTheDocument()
    expect(screen.queryByText(assessmentId)).not.toBeInTheDocument()
    expect(
      screen.queryByText('Post monitoring is unavailable'),
    ).not.toBeInTheDocument()
  })

  it('fails safely when an authenticated endpoint returns malformed JSON data', async () => {
    const fake = client({
      draftAssessment: vi
        .fn()
        .mockResolvedValue({ assessment_id: assessmentId }),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'saved assessment response was invalid',
    )
  })

  it.each([
    ['metric', { metrics: [{ metric: 'replies' }] }],
    [
      'comparable evidence',
      { comparable_evidence: [{ post_id: assessmentId }] },
    ],
    ['observation', { observations: [{ kind: 'outlier' }] }],
    ['limitation string', { limitations: ['valid', 42] }],
  ] as const)(
    'rejects malformed nested %s assessment data instead of filtering it',
    async (_field, invalidFields) => {
      const fake = client({
        draftAssessment: vi.fn().mockResolvedValue({
          ...assessment,
          ...invalidFields,
        }),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'saved assessment response was invalid',
      )
      expect(
        screen.queryByText('Original Distribution Outlook'),
      ).not.toBeInTheDocument()
      expect(fake.publication).not.toHaveBeenCalled()
    },
  )

  it.each([
    [401, 'Authentication failed.'],
    [403, 'Rights denied.'],
    [404, 'Assessment missing.'],
    [422, 'Validation failed.'],
    [429, 'Rate limited.'],
    [503, 'Service unavailable.'],
  ] as const)(
    'renders a safe state for assessment GET %s without attempting publication POST',
    async (status, message) => {
      const fake = client({
        draftAssessment: vi.fn().mockRejectedValue(
          new ApiRequestError({
            status,
            code: `assessment_${status}`,
            message,
          }),
        ),
      })
      render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
      expect(await screen.findByRole('alert')).toHaveTextContent(message)
      expect(
        screen.queryByText(publication.external_post_id),
      ).not.toBeInTheDocument()
      expect(fake.publication).not.toHaveBeenCalled()
      expect(fake.linkPublication).not.toHaveBeenCalled()
    },
  )

  it('renders a safe state for assessment GET network failure and does not retry billable work', async () => {
    const fake = client({
      draftAssessment: vi.fn().mockRejectedValue(
        new ApiRequestError({
          status: null,
          code: 'network_error',
          message: 'The API could not be reached.',
        }),
      ),
    })
    render(<PostMonitoring assessmentId={assessmentId} client={fake} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The API could not be reached',
    )
    expect(fake.draftAssessment).toHaveBeenCalledTimes(1)
    expect(fake.publication).not.toHaveBeenCalled()
    expect(fake.linkPublication).not.toHaveBeenCalled()
  })
})

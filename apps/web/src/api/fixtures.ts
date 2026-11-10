import type { components } from './generated/schema'

export const healthFixture = { status: 'ok' } satisfies Record<string, string>

export const sessionFixture = {
  authenticated: true,
  csrf_token: 'synthetic-csrf-token',
} satisfies components['schemas']['SessionResponse']

export const errorFixture = {
  error: {
    code: 'authentication_required',
    message: 'A private creator session is required.',
    fields: null,
  },
} satisfies components['schemas']['ErrorResponse']

export const profileFixture = {
  status: 'configured',
  profile: {
    creator_key: '00000000-0000-0000-0000-000000000379',
    revision: 1,
    version: 'creator-goals-v1',
    recorded_at: '2026-11-09T12:00:00Z',
    niche: 'Independent product design',
    intended_audience: 'Early-stage product teams',
    priority_outcomes: ['conversation'],
    preferred_styles: ['personal_story'],
    language: 'en',
  },
} satisfies components['schemas']['CreatorProfileStateResponse']

export const permissionFixture = {
  personal_history: 'granted',
  personal_history_revision: 1,
  recorded_at: '2026-11-09T12:01:00Z',
  x_history_processing: 'blocked',
  niche_discovery: 'unavailable',
  external_synthesis: 'disabled',
} satisfies components['schemas']['DataPermissionResponse']

export const reportFixture = {
  id: '00000000-0000-0000-0000-000000000380',
  creator_key: '00000000-0000-0000-0000-000000000379',
  generated_at: '2026-11-09T12:02:00Z',
  as_of: '2026-11-09T12:02:00Z',
  goals_revision: 1,
  goals_version: 'creator-goals-v1',
  evidence_version: 'creator-report-evidence-v2',
  report_version: 'creator-intelligence-report-v2',
  baseline_version: 'creator-baseline-v1',
  processing_status: 'completed',
  coverage: 'personal_only_partial',
  freshness: { personal_history: 'historical', niche_discovery: 'unavailable' },
  processing_permissions: {
    personal_history: { status: 'blocked_by_source_policy' },
    niche_discovery: { status: 'unavailable', external_requests: 0 },
    external_synthesis: { status: 'disabled', provider_calls: 0 },
  },
  limitations: [
    'Niche discovery is unavailable and was not requested; this endpoint makes no external request.',
    'No available creator-owned canonical history is available yet.',
  ],
  evidence: { sources: [], observations: [], profiles: [] },
  report: {
    state: 'personal_only_partial',
    personal_findings: [],
    niche_findings: [],
    experiments: [],
    opportunities: [],
    personal_cohorts: [],
    content_patterns: [],
    limitations: [],
    synthesis_mode: 'deterministic_fallback',
  },
} satisfies components['schemas']['CreatorReportResponse']

export const latestReportFixture = {
  status: 'available',
  latest_report: reportFixture,
} satisfies components['schemas']['CreatorReportStateResponse']

export const draftAnalysisFixture = {
  assessment_id: '00000000-0000-0000-0000-000000000360',
  input_fingerprint: 'synthetic-draft-fingerprint',
  assessed_at: '2026-11-10T12:00:00Z',
  versions: {
    decision: 'decision-v1',
    decision_config: 'decision-config-v1',
    retrieval: 'retrieval-v1',
    ranking_config: 'ranking-v1',
    baseline: 'creator-baseline-v1',
    profile: 'profile-v1',
    embedding_identity: 'embedding-v1',
  },
  decision_state: 'supported',
  retrieval_state: 'matched',
  retrieval_candidate_count: 4,
  retrieval_vector_candidate_count: 2,
  retrieval_eligible_count: 2,
  retrieval_excluded_count: 2,
  retrieval_truncated: false,
  retrieval_exclusions: [],
  retrieval_coverage_limitations: [],
  comparable_evidence: [
    {
      post_id: '00000000-0000-0000-0000-000000000361',
      relevance: 0.86,
      components: {
        semantic: 0.9,
        topic: 0.8,
        intent: 0.8,
        format: null,
        structure: null,
      },
      retrieval_position: 1,
      inclusion_reasons: ['Same declared intent', 'Comparable topic evidence'],
    },
  ],
  metrics: [
    {
      metric: 'replies',
      metric_definition: 'public_reply_count_v1',
      window: 'age:24h',
      evidence_strength: 'Moderate',
      coverage: 1,
      eligible_post_count: 2,
      effective_sample_size: 1.7,
      supporting_post_ids: ['00000000-0000-0000-0000-000000000361'],
      statistics: null,
      exclusion_counts: [],
      limitations: [],
      outlook: {
        kind: 'age_aligned',
        lower_p25: 2,
        median_p50: 5,
        upper_p75: 9,
        comparable_post_ids: ['00000000-0000-0000-0000-000000000361'],
        effective_sample_size: 1.7,
      },
    },
  ],
  observations: [
    {
      kind: 'repeatability',
      explanation:
        'The comparable posts show a repeatable reply range rather than a single outlier.',
      supporting_post_ids: ['00000000-0000-0000-0000-000000000361'],
      metric: 'replies',
      metric_definition: 'public_reply_count_v1',
      window: 'age:24h',
      evidence_strength: 'Moderate',
      evidence_statistics: null,
      limitations: [],
    },
  ],
  suggested_hypothesis: {
    kind: 'experiment_hypothesis',
    label: 'Keep the question-led opening',
    variable: 'opening structure',
    value: 'question-led',
    rationale:
      'The matched history contains more than one question-led post with observed replies.',
    supporting_post_ids: ['00000000-0000-0000-0000-000000000361'],
    comparison_post_ids: ['00000000-0000-0000-0000-000000000361'],
    metric: 'replies',
    metric_definition: 'public_reply_count_v1',
    window: 'age:24h',
    is_optional: true,
  },
  accepted_hypothesis: null,
  assumptions: ['Only permitted creator-owned evidence is included.'],
  limitations: ['This is an association, not a causal estimate.'],
  exclusions: [['insufficient_observation', 1] as [string, number]],
} satisfies components['schemas']['DraftAnalysisResponse']

export const evidenceFixture = {
  items: [
    {
      id: '00000000-0000-0000-0000-000000000361',
      published_at: '2026-11-01T12:00:00Z',
      source: 'authorized_x_api',
      text: "Which product decision changed your team's week?",
      source_url: 'https://x.com/i/status/1234567890',
      disclosure: 'permitted',
      source_observed_at: '2026-11-01T12:01:00Z',
      freshness: 'recorded',
      observations: [
        {
          id: '00000000-0000-0000-0000-000000000362',
          metric_name: 'replies',
          metric_definition: 'public_reply_count_v1',
          metric_unit: 'replies',
          metric_value: '5',
          state: 'observed',
          window_kind: 'age_aligned',
          window_key: 'age:24h',
          observed_at: '2026-11-02T12:00:00Z',
          published_at: '2026-11-01T12:00:00Z',
          observed_age_seconds: 86400,
          provenance: { source: 'authorized_x_api' },
          source: 'authorized_x_api',
        },
      ],
      observations_truncated: false,
    },
  ],
  as_of: '2026-11-10T12:00:00Z',
  assessment_id: '00000000-0000-0000-0000-000000000360',
} satisfies components['schemas']['EvidencePage']

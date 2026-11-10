import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { DraftAnalysis } from './DraftAnalysis'
import { createApiClient } from './api/client'
import { draftAnalysisFixture, evidenceFixture } from './api/fixtures'
import { apiHandlers } from './api/mocks'

const server = setupServer(...apiHandlers)

beforeAll(() => server.listen())
afterAll(() => server.close())
beforeEach(() => server.resetHandlers())

const context = {
  creatorKey: '00000000-0000-0000-0000-000000000379',
  reportId: '00000000-0000-0000-0000-000000000380',
  goalsRevision: 1,
  reportAsOf: '2026-11-09T12:02:00Z',
  coverage: 'personal_only_partial',
} as const

describe('DraftAnalysis with the generated API client', () => {
  it('sends the contract body and idempotency header, then enriches by assessment id', async () => {
    let requestBody: unknown
    let idempotencyKey: string | null = null
    server.use(
      http.post(
        '*/api/v1/creators/me/draft-assessments',
        async ({ request }) => {
          requestBody = await request.json()
          idempotencyKey = request.headers.get('Idempotency-Key')
          return HttpResponse.json(draftAnalysisFixture, { status: 201 })
        },
      ),
    )
    render(<DraftAnalysis context={context} client={createApiClient()} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'A question-led draft for product teams.' },
    })
    fireEvent.change(screen.getByLabelText(/Topic/), {
      target: { value: 'Product discovery' },
    })
    fireEvent.change(screen.getByLabelText(/Intent/), {
      target: { value: 'ask' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    expect(
      await screen.findByText('What the evidence suggests trying next'),
    ).toBeInTheDocument()
    expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)
    expect(requestBody).toMatchObject({
      text: 'A question-led draft for product teams.',
      declared_topic: 'Product discovery',
      declared_intent: 'ask',
      topology: 'original',
      metric_preferences: [],
    })
    expect(await screen.findByText('Open permitted source')).toBeInTheDocument()
    expect(
      await screen.findByText(
        "Which product decision changed your team's week?",
      ),
    ).toBeInTheDocument()
    expect(evidenceFixture.items[0].id).toBe(
      draftAnalysisFixture.comparable_evidence[0].post_id,
    )
  })

  it('retrieves the saved assessment using its canonical assessment id', async () => {
    render(<DraftAnalysis context={context} client={createApiClient()} />)
    fireEvent.change(screen.getByLabelText('Draft text'), {
      target: { value: 'Saved assessment draft' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze this draft' }))
    await screen.findByText('What the evidence suggests trying next')
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh saved assessment' }),
    )
    await waitFor(() =>
      expect(
        screen.getByText('Assessment 00000000-0000-0000-0000-000000000360'),
      ).toBeInTheDocument(),
    )
  })
})

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

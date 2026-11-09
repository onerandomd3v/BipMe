import { http, HttpResponse } from 'msw'
import { healthFixture, sessionFixture } from './fixtures'

export const apiHandlers = [
  http.get('*/api/health', () => HttpResponse.json(healthFixture)),
  http.get('*/api/auth/session', () => HttpResponse.json(sessionFixture)),
  http.post('*/api/auth/private/session', () =>
    HttpResponse.json(sessionFixture),
  ),
  http.post('*/api/auth/logout', () => new HttpResponse(null, { status: 204 })),
]

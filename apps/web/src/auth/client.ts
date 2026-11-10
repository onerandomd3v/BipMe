import { ApiRequestError, apiClient, type ApiClient } from '../api/client'

export { ApiRequestError as ApiResponseError }

export type PrivateSession = Awaited<ReturnType<ApiClient['session']>>
export type XConnection = {
  connected: boolean
  state: string | null
  scopes: string[]
  expires_at: string | null
}

/** COD-356 owns transport, cookies, generated types, errors, and in-memory CSRF. */
export function createAuthApi(client: ApiClient) {
  return {
    readSession: client.session,
    createPrivateSession: client.privateSession,
    readXConnection: async (signal?: AbortSignal): Promise<XConnection> => {
      const response = await client.xConnection(signal)
      return {
        connected: response.connected,
        state: response.state ?? null,
        scopes: response.scopes,
        expires_at: response.expires_at ?? null,
      }
    },
    refreshXConnection: async (signal?: AbortSignal): Promise<XConnection> => {
      const response = await client.refreshXConnection(signal)
      return {
        connected: response.connected,
        state: response.state ?? null,
        scopes: response.scopes,
        expires_at: response.expires_at ?? null,
      }
    },
    disconnectXConnection: client.disconnectXConnection,
    logout: client.logout,
  }
}

export const authApi = createAuthApi(apiClient)

export function getXAuthorizationUrl() {
  const query = new URLSearchParams({ return_to: '/connections' })
  return `/api/auth/x/authorize?${query.toString()}`
}

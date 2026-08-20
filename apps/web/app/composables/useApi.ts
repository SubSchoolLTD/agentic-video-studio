export interface ApiError {
  error?: {
    code?: string
    message?: string
    request_id?: string
    details?: Record<string, unknown>
    retryable?: boolean
  }
}

export function useApi() {
  const config = useRuntimeConfig()
  const auth = useAuth()
  const projectId = auth.projectId

  async function api<T>(path: string, options: Record<string, unknown> = {}): Promise<T> {
    const headers: Record<string, string> = {
      ...(auth.accessToken.value ? { Authorization: `Bearer ${auth.accessToken.value}` } : {}),
      ...(auth.organizationId.value ? { 'X-Organization-ID': auth.organizationId.value } : {}),
      ...((options.headers as Record<string, string> | undefined) || {}),
    }
    try {
      return await $fetch<T>(path, {
        baseURL: config.public.apiBase,
        ...options,
        headers,
      })
    }
    catch (error: any) {
      if (error?.response?.status === 401 && !path.startsWith('/v1/auth/') && await auth.refresh()) {
        return api<T>(path, options)
      }
      const payload = error?.data as ApiError | undefined
      const message = payload?.error?.message || error?.message || 'The request could not be completed.'
      throw Object.assign(new Error(message), {
        requestId: payload?.error?.request_id,
        status: error?.response?.status,
        code: payload?.error?.code,
        details: payload?.error?.details,
        retryable: payload?.error?.retryable,
      })
    }
  }

  return { api, projectId, apiBase: config.public.apiBase }
}

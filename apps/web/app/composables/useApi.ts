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
  const route = useRoute()
  const nuxtApp = useNuxtApp()
  const projectId = auth.projectId

  async function api<T>(path: string, options: Record<string, unknown> = {}, alreadyRefreshed = false): Promise<T> {
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
      const payload = error?.data as ApiError | undefined
      // Older API revisions used 401 for a rejected social password/code too.
      // Never replay those credentials or revoke a valid Framewise session.
      const providerFailure = payload?.error?.details?.auth_scope === 'provider'
        || (['instagram', 'tiktok'].includes(String(payload?.error?.details?.provider || ''))
          && /\/connections\/(?:[^/]+\/)?browser-(?:login|verify)$/.test(path))
      if (error?.response?.status === 401 && !providerFailure && !path.startsWith('/v1/auth/')) {
        if (!alreadyRefreshed && await auth.refresh()) return api<T>(path, options, true)
        auth.clearSession()
        const redirect = route.fullPath && !route.path.startsWith('/login') ? `?redirect=${encodeURIComponent(route.fullPath)}` : ''
        await nuxtApp.runWithContext(() => navigateTo(`/login${redirect}`))
      }
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

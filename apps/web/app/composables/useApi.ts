export interface ApiError {
  error?: {
    code?: string
    message?: string
    request_id?: string
  }
}

export function useApi() {
  const config = useRuntimeConfig()
  const projectId = useState<string>('active-project', () => 'prj_subschool')

  async function api<T>(path: string, options: Record<string, unknown> = {}): Promise<T> {
    const headers = {
      Authorization: `Bearer ${config.public.demoToken}`,
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
      const message = payload?.error?.message || error?.message || 'The request could not be completed.'
      throw Object.assign(new Error(message), { requestId: payload?.error?.request_id })
    }
  }

  return { api, projectId, apiBase: config.public.apiBase }
}


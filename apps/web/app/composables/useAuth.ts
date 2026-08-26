interface SessionUser {
  id: string
  email: string
  display_name: string
  status: string
  role: string
  organization_id: string
  default_project_id?: string | null
  is_platform_admin: boolean
}

interface SessionPayload {
  access_token: string
  refresh_token: string
  expires_in: number
  organization_id: string
  default_project_id?: string | null
  user?: SessionUser
}

export function useAuth() {
  const config = useRuntimeConfig()
  const nuxtApp = useNuxtApp() as ReturnType<typeof useNuxtApp> & { _avsRefreshPromise?: Promise<boolean> | null }
  const accessCookie = useCookie<string | null>('avs_access', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 30 })
  const refreshCookie = useCookie<string | null>('avs_refresh', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 30 })
  const organizationCookie = useCookie<string | null>('avs_organization', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 365 })
  const projectCookie = useCookie<string | null>('avs_project', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 365 })
  const accessToken = useState<string | null>('session-access-token', () => accessCookie.value)
  const refreshToken = useState<string | null>('session-refresh-token', () => refreshCookie.value)
  const organizationId = useState<string | null>('session-organization', () => organizationCookie.value)
  const user = useState<SessionUser | null>('session-user', () => null)
  const projectId = useState<string>('active-project', () => projectCookie.value || '')

  function setSession(payload: SessionPayload) {
    accessToken.value = payload.access_token
    accessCookie.value = payload.access_token
    refreshToken.value = payload.refresh_token
    refreshCookie.value = payload.refresh_token
    organizationId.value = payload.organization_id
    organizationCookie.value = payload.organization_id
    if (payload.default_project_id) {
      projectCookie.value = payload.default_project_id
      projectId.value = payload.default_project_id
    }
    if (payload.user) user.value = payload.user
  }

  function clearSession() {
    accessToken.value = null
    accessCookie.value = null
    refreshToken.value = null
    refreshCookie.value = null
    organizationId.value = null
    organizationCookie.value = null
    projectCookie.value = null
    projectId.value = ''
    user.value = null
  }

  async function login(email: string, password: string) {
    const payload = await $fetch<SessionPayload>('/v1/auth/login', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { email, password },
    })
    setSession(payload)
    return payload
  }

  async function refresh(): Promise<boolean> {
    if (!refreshToken.value) return false
    const rotate = () => $fetch<SessionPayload>('/v1/auth/refresh', {
        baseURL: config.public.apiBase,
        method: 'POST',
        body: { token: refreshToken.value },
      }).then((payload) => {
        setSession(payload)
        return true
      }).catch(() => {
        clearSession()
        return false
      })
    // The Nuxt app is request-scoped on SSR and singleton in the browser. Keeping the
    // promise here prevents concurrent page loaders from replaying one rotating token.
    if (!nuxtApp._avsRefreshPromise) {
      nuxtApp._avsRefreshPromise = rotate().finally(() => { nuxtApp._avsRefreshPromise = null })
    }
    return nuxtApp._avsRefreshPromise
  }

  async function loadMe(alreadyRefreshed = false): Promise<SessionUser | null> {
    if (!accessToken.value) {
      if (alreadyRefreshed || !await refresh()) return null
    }
    try {
      const payload = await $fetch<any>('/v1/me', {
        baseURL: config.public.apiBase,
        headers: {
          Authorization: `Bearer ${accessToken.value}`,
          ...(organizationId.value ? { 'X-Organization-ID': organizationId.value } : {}),
        },
      })
      user.value = {
        id: payload.actor_id,
        email: payload.email,
        display_name: payload.display_name,
        status: 'active',
        role: payload.role,
        organization_id: payload.organization_id,
        default_project_id: projectId.value,
        is_platform_admin: Boolean(payload.is_platform_admin),
      }
      return user.value
    }
    catch (error: any) {
      if (!alreadyRefreshed && error?.response?.status === 401 && await refresh()) return loadMe(true)
      return null
    }
  }

  async function logout() {
    const raw = refreshToken.value
    clearSession()
    if (raw) {
      await $fetch('/v1/auth/logout', {
        baseURL: config.public.apiBase,
        method: 'POST',
        body: { token: raw },
      }).catch(() => undefined)
    }
    await navigateTo('/login')
  }

  return { accessToken, refreshToken, organizationId, projectId, user, setSession, clearSession, login, refresh, loadMe, logout }
}

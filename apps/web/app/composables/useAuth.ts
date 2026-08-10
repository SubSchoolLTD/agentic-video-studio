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

let refreshPromise: Promise<boolean> | null = null

export function useAuth() {
  const config = useRuntimeConfig()
  const accessToken = useCookie<string | null>('avs_access', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 30 })
  const refreshToken = useCookie<string | null>('avs_refresh', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 30 })
  const organizationId = useCookie<string | null>('avs_organization', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 365 })
  const projectCookie = useCookie<string | null>('avs_project', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 365 })
  const user = useState<SessionUser | null>('session-user', () => null)
  const projectId = useState<string>('active-project', () => projectCookie.value || '')

  function setSession(payload: SessionPayload) {
    accessToken.value = payload.access_token
    refreshToken.value = payload.refresh_token
    organizationId.value = payload.organization_id
    if (payload.default_project_id) {
      projectCookie.value = payload.default_project_id
      projectId.value = payload.default_project_id
    }
    if (payload.user) user.value = payload.user
  }

  function clearSession() {
    accessToken.value = null
    refreshToken.value = null
    organizationId.value = null
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
    if (!refreshPromise) {
      refreshPromise = $fetch<SessionPayload>('/v1/auth/refresh', {
        baseURL: config.public.apiBase,
        method: 'POST',
        body: { token: refreshToken.value },
      }).then((payload) => {
        setSession(payload)
        return true
      }).catch(() => {
        clearSession()
        return false
      }).finally(() => { refreshPromise = null })
    }
    return refreshPromise
  }

  async function loadMe() {
    if (!accessToken.value) return null
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
    catch {
      if (await refresh()) return loadMe()
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

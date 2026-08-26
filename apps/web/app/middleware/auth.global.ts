const publicRoutes = new Set(['/', '/login', '/register', '/verify-email', '/forgot-password', '/reset-password'])

export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuth()
  const isPublic = publicRoutes.has(to.path)
  if (isPublic) {
    if (!auth.accessToken.value && auth.refreshToken.value && ['/login', '/register'].includes(to.path)) await auth.refresh()
    if (auth.accessToken.value && ['/login', '/register'].includes(to.path)) return navigateTo('/app')
    return
  }
  if (!auth.accessToken.value && (!auth.refreshToken.value || !await auth.refresh())) return navigateTo(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
  if (!auth.user.value && !await auth.loadMe()) return navigateTo(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
  if (to.path.startsWith('/admin') && !auth.user.value?.is_platform_admin) return navigateTo('/app')
})

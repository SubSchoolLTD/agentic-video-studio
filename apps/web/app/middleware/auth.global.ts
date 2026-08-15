const publicRoutes = new Set(['/', '/login', '/register', '/verify-email', '/forgot-password', '/reset-password'])

export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuth()
  const isPublic = publicRoutes.has(to.path)
  if (isPublic) {
    if (auth.accessToken.value && ['/login', '/register'].includes(to.path)) return navigateTo('/app')
    return
  }
  if (!auth.accessToken.value) return navigateTo(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
  if (!auth.user.value && !await auth.loadMe()) return navigateTo('/login')
  if (to.path.startsWith('/admin') && !auth.user.value?.is_platform_admin) return navigateTo('/app')
})

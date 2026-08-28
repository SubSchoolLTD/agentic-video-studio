const publicRoutes = new Set(['/', '/login', '/register', '/verify-email', '/forgot-password', '/reset-password'])

export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuth()
  const isPublic = publicRoutes.has(to.path) || to.path === '/solutions' || to.path.startsWith('/solutions/')
  if (isPublic) {
    if (!auth.accessToken.value && auth.refreshToken.value && ['/login', '/register'].includes(to.path)) await auth.refresh()
    if (auth.accessToken.value && ['/login', '/register'].includes(to.path)) {
      if (!auth.user.value) await auth.loadMe()
      const requested = typeof to.query.redirect === 'string'
        && to.query.redirect.startsWith('/')
        && !to.query.redirect.startsWith('//')
        ? to.query.redirect
        : '/app'
      return navigateTo(auth.user.value?.onboarding_complete === false ? '/onboarding' : requested)
    }
    return
  }
  if (!auth.accessToken.value && (!auth.refreshToken.value || !await auth.refresh())) return navigateTo(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
  if (!auth.user.value && !await auth.loadMe()) return navigateTo(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
  if (auth.user.value?.onboarding_complete === false && to.path !== '/onboarding') return navigateTo('/onboarding')
  if (auth.user.value?.onboarding_complete !== false && to.path === '/onboarding') return navigateTo('/app')
  if (to.path.startsWith('/admin') && !auth.user.value?.is_platform_admin) return navigateTo('/app')
})

export default defineNuxtConfig({
  compatibilityDate: '2026-08-01',
  devtools: { enabled: false },
  css: ['~/assets/css/main.css'],
  modules: ['@nuxt/eslint'],
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000',
      grafanaUrl: process.env.NUXT_PUBLIC_GRAFANA_URL || '',
    },
  },
  app: {
    head: {
      title: 'Framewise — Agentic Video Studio',
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        { rel: 'manifest', href: '/site.webmanifest' },
      ],
      meta: [
        { name: 'description', content: 'Evidence-first autonomous video production for small media teams.' },
        { name: 'theme-color', content: '#17131f' },
        { 'http-equiv': 'Content-Security-Policy', content: "default-src 'self'; connect-src 'self' https: http://127.0.0.1:*; img-src 'self' data: https:; media-src 'self' https: http://127.0.0.1:*; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self' 'unsafe-inline'; font-src 'self' data: https://fonts.gstatic.com" },
      ],
    },
  },
  typescript: { strict: true, typeCheck: false },
})

export default defineNuxtConfig({
  compatibilityDate: '2026-08-01',
  devtools: { enabled: false },
  css: ['~/assets/css/main.css'],
  modules: ['@nuxt/eslint'],
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000',
      demoToken: process.env.NUXT_PUBLIC_DEMO_TOKEN || 'demo-token',
      grafanaUrl: process.env.NUXT_PUBLIC_GRAFANA_URL || '',
    },
  },
  app: {
    head: {
      title: 'Framewise — Agentic Video Studio',
      meta: [
        { name: 'description', content: 'Evidence-first autonomous video production for small media teams.' },
        { name: 'theme-color', content: '#17131f' },
      ],
    },
  },
  typescript: { strict: true, typeCheck: false },
})

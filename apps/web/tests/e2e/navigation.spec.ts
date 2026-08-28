import { expect, test } from '@playwright/test'
import { registerThroughApi, registerThroughUi } from './helpers'

const pages = [
  ['/app', 'Good morning, Navigation'],
  ['/sources', 'Context'],
  ['/research', 'Research radar'],
  ['/ideas', 'Ideas'],
  ['/characters', 'Characters'],
  ['/calendar', 'Calendar'],
  ['/productions', 'Productions'],
  ['/library', 'Library'],
  ['/publishing', 'Publishing'],
  ['/analytics', 'Analytics'],
  ['/strategy', 'Strategy memory'],
  ['/connections', 'Connections'],
  ['/developer', 'Developer'],
  ['/settings', 'Project settings'],
] as const

test('public landing page explains the product, pricing and account entry points', async ({ page }) => {
  const response = await page.goto('/')
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('heading', { name: /self-running video channel/i })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'From your website to an always-on content engine.' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Made without a human in the production loop.' })).toBeVisible()
  await expect(page.locator('.showcase-player video')).toHaveCount(3)
  await expect(page.locator('.showcase-player video').first()).toHaveAttribute('src', '/showcase/framewise-example-01.mp4')
  for (const source of ['01', '02', '03']) {
    const media = await page.request.get(`/showcase/framewise-example-${source}.mp4`)
    expect(media.ok()).toBe(true)
    expect(media.headers()['content-type']).toContain('video/mp4')
  }
  await expect(page.getByText('without manual editing, prompt rewrites or any other human intervention', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Pay as you generate' })).toBeVisible()
  await expect(page.locator('.pricing-value strong')).toHaveText('$12')
  await expect(page.getByText('No subscription or monthly platform fee')).toBeVisible()
  await expect(page.getByText('Promo codes add balance without payment')).toBeVisible()
  await expect(page.getByText('activate a promo code separately', { exact: false })).toBeVisible()
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', 'https://studio.subschool.us/')
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /automatic social video engine/i)
  await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(2)
  await expect(page.locator('footer').getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/register')
  await expect(page.locator('footer').getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Solutions' })).toHaveAttribute('href', '/solutions')
})

test('solution pages address distinct audiences', async ({ page }) => {
  const overview = await page.goto('/solutions')
  expect(overview?.status()).toBe(200)
  await expect(page.getByRole('heading', { name: /one autonomous studio/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /studios & media teams/i })).toHaveAttribute('href', '/solutions/studios-media-teams')
  for (const [slug, heading] of [
    ['studios-media-teams', /keep the story alive/i],
    ['creators-experts', /turn expertise into a channel/i],
    ['small-businesses', /stay visible every week/i],
    ['education-teams', /make useful educational video/i],
  ] as const) {
    const response = await page.goto(`/solutions/${slug}`)
    expect(response?.status(), slug).toBe(200)
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
})

test('all product sections render without route errors', async ({ page }) => {
  await registerThroughUi(page, 'Navigation')
  for (const [path, heading] of pages) {
    const response = await page.goto(path)
    expect(response?.status(), path).toBeLessThan(400)
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  }
})

test('registration creates an isolated tenant and logout protects the workspace', async ({ page, request }) => {
  const first = await registerThroughUi(page, 'Isolation')
  const firstProject = await page.request.get(`${process.env.E2E_API_BASE || 'http://127.0.0.1:8100'}/v1/projects/${first.projectId}`, {
    headers: { Authorization: `Bearer ${(await page.context().cookies()).find(item => item.name === 'avs_access')?.value}` },
  })
  expect(firstProject.status()).toBe(200)

  const second = await registerThroughApi(request, 'Other tenant')
  const crossTenant = await request.get(`${process.env.E2E_API_BASE || 'http://127.0.0.1:8100'}/v1/projects/${first.projectId}`, {
    headers: { Authorization: `Bearer ${second.access_token}` },
  })
  expect(crossTenant.status()).toBe(404)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL('/login')
  await expect(page.locator('.auth-layout')).toHaveAttribute('data-hydrated', 'true')
  await page.getByLabel('Email').fill(first.email)
  await page.getByLabel('Password').fill(first.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL('/app')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /self-running video channel/i })).toBeVisible()
  await page.goto('/app')
  await expect(page).toHaveURL(/\/login\?redirect=/)
})

test('browser session rotates an expired access token and redirects when refresh fails', async ({ page }) => {
  await registerThroughUi(page, 'Session rotation')
  const origin = new URL(page.url()).origin
  const before = await page.context().cookies()
  const firstRefresh = before.find(item => item.name === 'avs_refresh')?.value
  expect(firstRefresh).toMatch(/^avs_rt_/)

  await page.context().addCookies([{ name: 'avs_access', value: 'expired-access-token', url: origin }])
  await page.goto('/app')
  await expect(page).toHaveURL('/app')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  const rotated = await page.context().cookies()
  expect(rotated.find(item => item.name === 'avs_access')?.value).not.toBe('expired-access-token')
  expect(rotated.find(item => item.name === 'avs_refresh')?.value).not.toBe(firstRefresh)

  await page.context().addCookies([
    { name: 'avs_access', value: 'expired-again', url: origin },
    { name: 'avs_refresh', value: 'avs_rt_invalid_browser_session_token', url: origin },
  ])
  await page.goto('/app')
  await expect(page).toHaveURL(/\/login\?redirect=\/app/)
})

test('registration reports a transactional email failure honestly', async ({ page }) => {
  await page.route('**/v1/auth/register', async (route) => {
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'verification_required',
        email: 'delivery-test@example.com',
        email_sent: false,
      }),
    })
  })
  await page.goto('/register')
  await expect(page.locator('.auth-layout')).toHaveAttribute('data-hydrated', 'true')
  await page.getByLabel('Your name').fill('Delivery Test')
  await page.getByLabel('Work email').fill('delivery-test@example.com')
  await page.getByLabel('Password').fill('correct horse battery staple')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Workspace created' })).toBeVisible()
  await expect(page.getByText('the confirmation email could not be sent')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Check your email' })).toHaveCount(0)
})

test('social connection uses ordinary browser sign-in and export is not a connector', async ({ page }) => {
  await registerThroughUi(page, 'Social browser')
  await page.goto('/connections')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  await expect(page.getByRole('heading', { name: 'Export' })).toHaveCount(0)
  const tiktok = page.locator('.connection-card').filter({ hasText: 'TikTok' })
  await tiktok.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('heading', { name: 'Connect TikTok' })).toBeVisible()
  await page.getByLabel('Username or email').fill('creator@example.test')
  await page.getByLabel('Password').fill('transient-provider-password')
  const [login] = await Promise.all([
    page.waitForResponse(response => (
      response.url().includes('/connections/tiktok/browser-login') && response.request().method() === 'POST'
    )),
    page.getByRole('button', { name: 'Sign in securely' }).click(),
  ])
  expect(login.status()).toBe(200)
  await expect(page.getByText('Only the encrypted browser session was saved')).toBeVisible()
  await expect(tiktok).toContainText('@creator@example.test')
  await expect(page.getByRole('heading', { name: 'Connect TikTok' })).toHaveCount(0)
})

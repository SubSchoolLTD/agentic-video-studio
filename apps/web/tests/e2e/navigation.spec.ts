import { expect, test } from '@playwright/test'
import { registerThroughApi, registerThroughUi } from './helpers'

const pages = [
  ['/app', 'Good morning, Navigation'],
  ['/sources', 'Sources'],
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
  await expect(page.getByRole('heading', { name: /checks the facts/i })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'From your website to a production system.' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Pay as you generate' })).toBeVisible()
  await expect(page.locator('.pricing-value strong')).toHaveText('$12')
  await expect(page.getByText('No subscription or monthly platform fee')).toBeVisible()
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', 'https://studio.subschool.us/')
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /evidence-backed social video/i)
  await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(2)
  await expect(page.locator('footer').getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/register')
  await expect(page.locator('footer').getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
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
  await expect(page.getByRole('heading', { name: /checks the facts/i })).toBeVisible()
  await page.goto('/app')
  await expect(page).toHaveURL(/\/login\?redirect=/)
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
  await page.getByLabel('Organization').fill('Delivery Test Organization')
  await page.getByLabel('Project name').fill('Delivery Test Project')
  await page.getByLabel('Project website').fill('https://example.com')
  await page.getByRole('button', { name: 'Create private workspace' }).click()
  await expect(page.getByRole('heading', { name: 'Workspace created' })).toBeVisible()
  await expect(page.getByText('the confirmation email could not be sent')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Check your email' })).toHaveCount(0)
})

test('social connection buttons start the provider authorization page and export is not a connector', async ({ page }) => {
  await registerThroughUi(page, 'Social OAuth')
  let oauthStarted = false
  await page.route('**/v1/projects/*/connections/tiktok/authorize', async (route) => {
    oauthStarted = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ authorize_url: 'https://www.tiktok.com/v2/auth/authorize/?client_key=e2e' }),
    })
  })
  await page.route('https://www.tiktok.com/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>TikTok authorization</h1>' })
  })
  await page.goto('/connections')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  await expect(page.getByRole('heading', { name: 'Export' })).toHaveCount(0)
  const tiktok = page.locator('.connection-card').filter({ hasText: 'TikTok' })
  await page.evaluate(() => {
    window.open = () => null
  })
  const [oauth] = await Promise.all([
    page.waitForResponse(response => (
      response.url().includes('/connections/tiktok/authorize') && response.request().method() === 'POST'
    )),
    tiktok.getByRole('button', { name: 'Connect' }).click(),
  ])
  expect(oauth.status()).toBe(200)
  expect(oauthStarted).toBe(true)
  await expect(page).toHaveURL(/tiktok\.com\/v2\/auth\/authorize/)
})

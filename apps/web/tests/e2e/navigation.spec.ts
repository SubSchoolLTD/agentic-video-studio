import { expect, test } from '@playwright/test'
import { registerThroughApi, registerThroughUi } from './helpers'

const pages = [
  ['/', 'Good morning, Navigation'],
  ['/sources', 'Sources'],
  ['/research', 'Research radar'],
  ['/ideas', 'Ideas'],
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
  await expect(page).toHaveURL('/')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.goto('/')
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

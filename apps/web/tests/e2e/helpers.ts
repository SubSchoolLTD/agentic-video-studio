import { expect, type APIRequestContext, type Page } from '@playwright/test'

const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:8100'
const testSecret = 'framewise-e2e-support'

export async function verificationToken(request: APIRequestContext, email: string, kind = 'verify_email') {
  const response = await request.get(`${apiBase}/v1/auth/test-support/email-token`, {
    headers: { 'X-Test-Support-Secret': testSecret },
    params: { email, kind },
  })
  expect(response.status(), await response.text()).toBe(200)
  return (await response.json()).token as string
}

export async function registerThroughUi(page: Page, label = 'E2E') {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
  const email = `framewise-${suffix}@example.com`
  const password = 'correct horse battery staple'
  const projectName = `${label} Project ${suffix}`
  await page.goto('/register')
  await expect(page.locator('.auth-layout')).toHaveAttribute('data-hydrated', 'true')
  await page.getByLabel('Your name').fill(`${label} Owner`)
  await page.getByLabel('Work email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByLabel('Organization').fill(`${label} Organization ${suffix}`)
  await page.getByLabel('Project name').fill(projectName)
  await page.getByLabel('Project website').fill(`https://${suffix}.example.com`)
  const invalid = await page.locator('input:invalid').evaluateAll(nodes => nodes.map((node: HTMLInputElement) => ({ name: node.name, message: node.validationMessage, value: node.value })))
  expect(invalid).toEqual([])
  const registrationResponse = page.waitForResponse(response => response.url().endsWith('/v1/auth/register') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create private workspace' }).click()
  const response = await registrationResponse
  expect(response.status(), await response.text()).toBe(201)
  expect((await response.json()).email_sent).toBe(true)
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  const token = await verificationToken(page.request, email)
  await page.goto(`/verify-email?token=${encodeURIComponent(token)}`)
  await expect(page).toHaveURL('/app', { timeout: 15_000 })
  const cookies = await page.context().cookies()
  const projectId = cookies.find(item => item.name === 'avs_project')?.value
  expect(projectId).toMatch(/^prj_/)
  return { email, password, projectName, projectId: projectId! }
}

export async function registerThroughApi(request: APIRequestContext, label = 'API E2E') {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
  const email = `framewise-api-${suffix}@example.com`
  const response = await request.post(`${apiBase}/v1/auth/register`, {
    data: {
      email,
      password: 'correct horse battery staple',
      display_name: `${label} Owner`,
      organization_name: `${label} Organization ${suffix}`,
      project_name: `${label} Project`,
      website_url: `https://${suffix}.example.com`,
      timezone: 'UTC',
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  const token = await verificationToken(request, email)
  const verified = await request.post(`${apiBase}/v1/auth/verify-email`, { data: { token } })
  expect(verified.status(), await verified.text()).toBe(200)
  return await verified.json() as { access_token: string, organization_id: string, default_project_id: string }
}

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
  const projectName = 'My project'
  await page.goto('/register')
  await expect(page.locator('.auth-layout')).toHaveAttribute('data-hydrated', 'true')
  await page.getByLabel('Your name').fill(`${label} Owner`)
  await page.getByLabel('Work email').fill(email)
  await page.getByLabel('Password').fill(password)
  const invalid = await page.locator('input:invalid').evaluateAll(nodes => nodes.map((node: HTMLInputElement) => ({ name: node.name, message: node.validationMessage, value: node.value })))
  expect(invalid).toEqual([])
  const registrationResponse = page.waitForResponse(response => response.url().endsWith('/v1/auth/register') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create account' }).click()
  const response = await registrationResponse
  expect(response.status(), await response.text()).toBe(201)
  expect((await response.json()).email_sent).toBe(true)
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  const token = await verificationToken(page.request, email)
  await page.goto(`/verify-email?token=${encodeURIComponent(token)}`)
  await expect(page).toHaveURL('/onboarding', { timeout: 15_000 })
  const cookies = await page.context().cookies()
  const projectId = cookies.find(item => item.name === 'avs_project')?.value
  const accessToken = cookies.find(item => item.name === 'avs_access')?.value
  expect(projectId).toMatch(/^prj_/)
  const headers = { Authorization: `Bearer ${accessToken}` }
  const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:8100'
  expect((await page.request.post(`${apiBase}/v1/projects/${projectId}/onboarding/website`, { headers, data: { website_url: `https://${suffix}.example.com` } })).status()).toBe(202)
  expect((await page.request.patch(`${apiBase}/v1/projects/${projectId}/onboarding/preferences`, { headers, data: { selling_percent: 20, viral_percent: 30, informative_percent: 50, videos_per_week: 3, average_duration_seconds: 30, audio_quality: 'premium', automation_mode: 'research_only' } })).status()).toBe(200)
  expect((await page.request.patch(`${apiBase}/v1/projects/${projectId}/onboarding/context`, { headers, data: { product_essence: `${label} test product`, target_audience: 'Test creators', problem_statement: 'They need reliable content', solution_summary: 'The product builds a repeatable workflow', product_keywords: [label], problem_keywords: ['content workflow'], audience_interest_keywords: ['creator tools'] } })).status()).toBe(200)
  expect((await page.request.post(`${apiBase}/v1/projects/${projectId}/onboarding/complete`, { headers })).status()).toBe(200)
  await page.goto('/app')
  await expect(page).toHaveURL('/app')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  return { email, password, projectName, projectId: projectId! }
}

export async function creditTestBalance(request: APIRequestContext, email: string, amountCents = 100_000) {
  const response = await request.post(`${apiBase}/v1/auth/test-support/balance`, {
    headers: { 'X-Test-Support-Secret': testSecret },
    data: { email, amount_cents: amountCents },
  })
  expect(response.status(), await response.text()).toBe(200)
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
  return {
    ...(await verified.json() as { access_token: string, organization_id: string, default_project_id: string }),
    email,
  }
}

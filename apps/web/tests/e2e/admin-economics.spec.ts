import { expect, test } from '@playwright/test'
import { registerThroughUi } from './helpers'

const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:8100'

test('admin reviews analytics, changes model pricing, issues and redeems a promo code', async ({ page }) => {
  const account = await registerThroughUi(page, 'Admin economics')
  const promoted = await page.request.post(`${apiBase}/v1/auth/test-support/platform-admin`, {
    headers: { 'X-Test-Support-Secret': 'framewise-e2e-support' },
    data: { email: account.email },
  })
  expect(promoted.status(), await promoted.text()).toBe(200)

  await page.goto('/admin')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  await expect(page.getByRole('heading', { name: 'Platform admin' })).toBeVisible()
  await expect(page.getByText('Any authenticated activity on or after day 7')).toBeVisible()
  await expect(page.getByText('Paid/admin top-ups only')).toBeVisible()

  await page.getByRole('button', { name: 'Models & pricing' }).click()
  const characterPrice = page.locator('.pricing-table tbody tr').filter({ hasText: 'character.generate' })
  await expect(characterPrice.locator('input').nth(2)).toHaveValue('gemini-2.5-flash-image')
  const charge = characterPrice.locator('input[type=number]').nth(1)
  await charge.fill('26')
  const pricingResponse = page.waitForResponse(response => (
    response.url().endsWith('/v1/platform-admin/pricing/character.generate')
    && response.request().method() === 'PATCH'
  ))
  await characterPrice.getByRole('button', { name: 'Save' }).click()
  expect((await pricingResponse).status()).toBe(200)
  await expect(page.getByText('Price saved')).toBeVisible()

  await page.getByRole('button', { name: 'Promo codes' }).click()
  const promo = `E2E-${Math.random().toString(16).slice(2, 10).toUpperCase()}`
  const form = page.getByTestId('admin-promo-form')
  await form.getByLabel('Custom code').fill(promo)
  await form.getByRole('spinbutton', { name: 'AI tokens', exact: true }).fill('321')
  await form.getByRole('spinbutton', { name: 'Maximum redemptions', exact: true }).fill('1')
  await form.getByRole('button', { name: 'Create code' }).click()
  await expect(page.locator('.created-code')).toHaveText(promo)

  await page.goto('/billing')
  const balanceBefore = Number((await page.getByText('AI tokens', { exact: true }).locator('..').locator('strong').textContent())?.replaceAll(',', ''))
  await page.getByLabel('Promo code').fill(promo)
  await page.getByRole('button', { name: 'Apply code' }).click()
  await expect(page.getByText('Promo code redeemed')).toBeVisible()
  await expect(page.getByText('Previously redeemed')).toBeVisible()
  await expect(page.getByText(promo)).toBeVisible()
  const availableCard = page.locator('.metric-card').filter({ hasText: 'Available' })
  await expect(availableCard.locator('strong')).toHaveText((balanceBefore + 321).toLocaleString())
})

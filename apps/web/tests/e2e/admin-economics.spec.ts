import { expect, test } from '@playwright/test'
import { registerThroughApi, registerThroughUi } from './helpers'

const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:8100'

test('separate admin UI manages analytics, prices, balance promo codes and administrators', async ({ page, request }) => {
  const account = await registerThroughUi(page, 'Admin economics')
  const promoted = await page.request.post(`${apiBase}/v1/auth/test-support/platform-admin`, {
    headers: { 'X-Test-Support-Secret': 'framewise-e2e-support' },
    data: { email: account.email },
  })
  expect(promoted.status(), await promoted.text()).toBe(200)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL('/login')
  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password').fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL('/app')
  await page.goto('/admin')
  await expect(page.locator('.admin-shell')).toHaveAttribute('data-hydrated', 'true')
  await expect(page.getByRole('heading', { name: 'Platform analytics' })).toBeVisible()
  await expect(page.getByText('Any authenticated activity on or after day 7')).toBeVisible()
  await expect(page.getByText('Captured PayPal + admin records')).toBeVisible()

  await page.goto('/admin/pricing')
  await expect(page.locator('.admin-shell')).toHaveAttribute('data-hydrated', 'true')
  const characterPrice = page.locator('.pricing-list article').filter({ hasText: 'character.generate' })
  await expect(characterPrice.getByLabel('Model')).toHaveValue('gemini-2.5-flash-image')
  await characterPrice.getByLabel('Customer charge / unit, USD').fill('0.26')
  const pricingResponse = page.waitForResponse(response => (
    response.url().endsWith('/v1/platform-admin/pricing/character.generate')
    && response.request().method() === 'PATCH'
  ))
  await characterPrice.getByRole('button', { name: 'Save' }).click()
  expect((await pricingResponse).status()).toBe(200)
  await expect(page.getByText('Price saved')).toBeVisible()

  await page.goto('/admin/promos')
  await expect(page.locator('.admin-shell')).toHaveAttribute('data-hydrated', 'true')
  const promo = `E2E-${Math.random().toString(16).slice(2, 10).toUpperCase()}`
  await page.getByLabel('Custom code optional').fill(promo)
  await page.getByLabel('Balance credit, USD').fill('3.21')
  await expect(page.getByLabel('Balance credit, USD')).toHaveValue('3.21')
  await page.getByLabel('Maximum activations').fill('1')
  await page.getByRole('button', { name: 'Create promo' }).click()
  await expect(page.locator('.created-code')).toContainText(promo)
  const promoRow = page.locator('.promo-list > div').filter({ hasText: promo })
  await expect(promoRow).toContainText('$3.21 balance credit')

  const futureAdmin = await registerThroughApi(request, 'Future admin')
  await page.goto('/admin/admins')
  await expect(page.locator('.admin-shell')).toHaveAttribute('data-hydrated', 'true')
  const options = await page.locator('.grant-card select option').evaluateAll(nodes => nodes.map(node => ({
    label: node.textContent || '',
    value: (node as HTMLOptionElement).value,
  })))
  const candidate = options.find(item => item.label.includes(futureAdmin.email))
  expect(candidate).toBeTruthy()
  await page.locator('.grant-card select').selectOption(candidate!.value)
  await page.getByRole('button', { name: 'Grant access' }).click()
  await expect(page.getByText('Administrator added')).toBeVisible()
  const removable = page.locator('.admin-list .app-card').filter({ hasText: futureAdmin.email })
  await expect(removable).toBeVisible()
  await removable.getByRole('button', { name: 'Revoke' }).click()
  await expect(page.getByText('Administrator removed')).toBeVisible()

  await page.goto('/billing')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  await page.getByLabel('Promo code').fill(promo)
  await expect(page.getByLabel('Promo code')).toHaveValue(promo)
  const redeemResponse = page.waitForResponse(response => (
    response.url().endsWith('/v1/billing/promo-codes/redeem') && response.request().method() === 'POST'
  ))
  await page.getByRole('button', { name: 'Activate code' }).click()
  expect((await redeemResponse).status()).toBe(200)
  await expect(page.getByText('Promo code activated')).toBeVisible()
  await expect(page.locator('.billing-metric-value strong').first()).toHaveText('$3.21')
})

import { expect, test } from '@playwright/test'
import { verificationToken } from './helpers'

test('new email account completes guided website and automation onboarding', async ({ page }) => {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
  const email = `onboarding-${suffix}@example.com`
  await page.goto('/register')
  await expect(page.locator('main.auth-layout')).toHaveAttribute('data-hydrated', 'true')
  await page.getByLabel('Your name').fill('Onboarding Owner')
  await page.getByLabel('Work email').fill(email)
  await page.getByLabel('Password').fill('correct horse battery staple')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  const token = await verificationToken(page.request, email)
  await page.goto(`/verify-email?token=${encodeURIComponent(token)}`)
  await expect(page).toHaveURL('/onboarding')

  await page.getByTestId('onboarding-website').fill('https://example.com')
  await page.getByRole('button', { name: 'Analyze website' }).click()
  await expect(page.getByRole('heading', { name: 'How should your content plan feel?' })).toBeVisible()
  await expect(page.getByText('20%')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByLabel('Videos per week').fill('4')
  await page.getByLabel('Average duration, seconds').fill('35')
  await page.getByLabel('Sound quality').selectOption('standard')
  await page.getByLabel('Automation').selectOption('scripts')
  await page.getByRole('button', { name: 'Save & calculate' }).click()
  await expect(page.getByText(/Estimated from current model pricing/)).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Connect channels now or later.' })).toBeVisible()
  await page.getByTestId('onboarding-connect-tiktok').click()
  await expect(page.getByRole('heading', { name: 'Connect TikTok' })).toBeVisible()
  await page.getByLabel('Username or email').fill('onboarding-creator@example.test')
  await page.getByLabel('Password').fill('transient-provider-password')
  const [socialLogin] = await Promise.all([
    page.waitForResponse(response => response.url().includes('/connections/tiktok/browser-login')),
    page.getByRole('button', { name: 'Sign in securely' }).click(),
  ])
  expect(socialLogin.status()).toBe(200)
  await expect(page.getByText('Only the encrypted browser session was saved')).toBeVisible()
  await expect(page.getByTestId('onboarding-connect-tiktok')).toContainText('Connected')

  await page.getByTestId('onboarding-connect-instagram').click()
  await page.getByLabel('Username or email').fill('two-factor-creator')
  await page.getByLabel('Password').fill('transient-provider-password')
  await page.route('**/connections/instagram/browser-login', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'conne_onboarding_2fa', status: 'verification_required', verification_required: true, password_persisted: false }),
  }))
  await page.getByRole('button', { name: 'Sign in securely' }).click()
  await expect(page.getByLabel('One-time verification code')).toBeVisible()
  await page.route('**/v1/connections/conne_onboarding_2fa/browser-verify', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'conne_onboarding_2fa', status: 'active', verification_required: false }),
  }))
  await page.getByLabel('One-time verification code').fill('123456')
  await page.getByRole('button', { name: 'Verify account' }).click()
  await expect(page.getByText('The verified browser session is ready for automatic publishing.')).toBeVisible()
  await expect(page.getByTestId('onboarding-social-login')).toHaveCount(0)

  await page.getByTestId('onboarding-connect-youtube').click()
  await expect(page.getByText('The channel is ready for automatic publishing.')).toBeVisible()
  await expect(page.getByTestId('onboarding-connect-youtube')).toContainText('Connected')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Does this describe your project?' })).toBeVisible({ timeout: 40_000 })
  await page.getByTestId('complete-onboarding').click()
  await expect(page).toHaveURL('/app')

  await page.goto('/settings?tab=video')
  await expect(page.getByRole('heading', { name: 'Video defaults' })).toBeVisible()
  await expect(page.getByText('Standard · Google TTS').first()).toBeVisible()
})

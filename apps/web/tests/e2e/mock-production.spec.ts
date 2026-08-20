import { expect, test } from '@playwright/test'
import { creditTestBalance, registerThroughUi } from './helpers'

test('creates an idea, renders a mock production, approves and publishes it', async ({ page }) => {
  const account = await registerThroughUi(page, 'Production')
  await creditTestBalance(page.request, account.email, 10_000)
  let generationPayload: any
  await page.route('**/v1/projects/*/generation-jobs', async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') return route.continue()
    const payload = request.postDataJSON()
    generationPayload = payload
    await route.continue({
      postData: JSON.stringify({ ...payload, aspect_ratios: ['9:16'], target_duration_seconds: 8 }),
      headers: { ...request.headers(), 'content-type': 'application/json' },
    })
  })

  await page.goto('/ideas')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  await page.getByTestId('new-idea').click()
  const title = `E2E product workflow ${Date.now()}`
  await page.getByTestId('idea-title').fill(title)
  await page.getByLabel('Opening hook').fill('One focused idea can become a complete short-form story.')
  await page.getByLabel('Primary audience').fill('Product leaders')
  await page.getByTestId('save-idea').click()
  await expect(page.getByText('Idea added')).toBeVisible()

  const card = page.locator('.idea-card').filter({ hasText: title })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: 'Configure video' }).click()
  await expect(page.getByTestId('generation-config')).toBeVisible()
  await expect(page.getByText('Maximum production charge')).toBeVisible()
  await expect(page.getByText('$10.08', { exact: true })).toBeVisible()
  await expect(page.getByText('Workspace balance')).toBeVisible()
  await page.getByLabel('Target duration').fill('8')
  await page.getByLabel('Preferred scene count').fill('2')
  await page.getByLabel(/Allow the director/).uncheck()
  await expect(page.getByText('$1.92', { exact: true })).toBeVisible()
  await expect(page.getByLabel(/Burn captions into the video/)).not.toBeChecked()
  await page.getByTestId('start-generation').click()
  expect(generationPayload.burn_in_captions).toBe(false)
  const productionLink = card.getByRole('link', { name: 'Open production' })
  await expect(productionLink).toBeVisible({ timeout: 15_000 })
  await productionLink.click()
  await expect(page).toHaveURL(/\/productions\/[a-z]+_/)

  const approve = page.getByTestId('approve-video')
  await expect(approve).toBeVisible({ timeout: 60_000 })
  const video = page.getByTestId('video-preview')
  await expect(video).toBeVisible()
  await expect.poll(async () => video.evaluate((node: HTMLVideoElement) => node.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1)
  await expect(page.getByTestId('download-captions-srt')).toBeVisible()
  await expect(page.getByTestId('download-captions-vtt')).toBeVisible()

  await page.getByRole('button', { name: 'storyboard', exact: true }).click()
  const scenePreview = page.getByTestId('scene-preview-1')
  await expect(scenePreview).toBeVisible()
  await expect.poll(async () => scenePreview.evaluate((node: HTMLVideoElement) => node.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1)
  await page.getByRole('button', { name: 'Open scene preview' }).first().click()
  await expect(page.getByTestId('scene-modal-video')).toBeVisible()
  await page.getByRole('button', { name: 'Close', exact: true }).click()

  await approve.click()
  const publicationLink = page.getByRole('link', { name: /Prepare publication/ })
  await expect(publicationLink).toBeVisible()
  await publicationLink.click()
  await expect(page.getByRole('heading', { name: 'Publish composer' })).toBeVisible()

  await page.getByTestId('prepare-publication').click()
  await expect(page.locator('.publication-plan')).toBeVisible()
  await page.getByTestId('confirm-publication').click()
  await expect(page.getByText('Publication committed')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'published' }).first()).toBeVisible()
  const balance = await page.request.get(`${process.env.E2E_API_BASE || 'http://127.0.0.1:8100'}/v1/billing/summary`, {
    headers: { Authorization: `Bearer ${(await page.context().cookies()).find(item => item.name === 'avs_access')?.value}` },
  })
  expect(balance.status()).toBe(200)
  // Deterministic mock providers do not create a real provider bill: the reserve
  // is visible in the ledger and reconciled back after the successful render.
  expect((await balance.json()).balance_cents).toBe(10_000)
  const ledger = await page.request.get(`${process.env.E2E_API_BASE || 'http://127.0.0.1:8100'}/v1/billing/ledger`, {
    headers: { Authorization: `Bearer ${(await page.context().cookies()).find(item => item.name === 'avs_access')?.value}` },
  })
  expect(ledger.status()).toBe(200)
  const eventTypes = (await ledger.json()).items.map((item: any) => item.event_type)
  expect(eventTypes).toEqual(expect.arrayContaining(['ai_usage', 'ai_usage_refund']))
  expect(account.projectId).toMatch(/^prj_/)
})

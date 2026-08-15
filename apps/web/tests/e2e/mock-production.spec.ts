import { expect, test } from '@playwright/test'
import { registerThroughUi } from './helpers'

test('creates an idea, renders a mock production, approves and publishes it', async ({ page }) => {
  const account = await registerThroughUi(page, 'Production')
  await page.route('**/v1/projects/*/generation-jobs', async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') return route.continue()
    const payload = request.postDataJSON()
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
  await page.getByLabel('Target duration').fill('8')
  await page.getByLabel('Preferred scene count').fill('2')
  await page.getByLabel(/Allow the director/).uncheck()
  await page.getByTestId('start-generation').click()
  const productionLink = card.getByRole('link', { name: 'Open production' })
  await expect(productionLink).toBeVisible({ timeout: 15_000 })
  await productionLink.click()
  await expect(page).toHaveURL(/\/productions\/[a-z]+_/)

  const approve = page.getByTestId('approve-video')
  await expect(approve).toBeVisible({ timeout: 60_000 })
  const video = page.getByTestId('video-preview')
  await expect(video).toBeVisible()
  await expect.poll(async () => video.evaluate((node: HTMLVideoElement) => node.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1)

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
  expect((await balance.json()).balance_tokens).toBeLessThan(1000)
  expect(account.projectId).toMatch(/^prj_/)
})

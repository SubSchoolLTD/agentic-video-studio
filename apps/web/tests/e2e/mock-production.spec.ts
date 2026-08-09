import { expect, test } from '@playwright/test'

test('creates an idea, renders a mock production, approves and publishes it', async ({ page }) => {
  await page.route('**/v1/projects/prj_subschool/generation-jobs', async (route) => {
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
  const title = `E2E teaching workflow ${Date.now()}`
  await page.getByTestId('idea-title').fill(title)
  await page.getByLabel('Opening hook').fill('One lesson can become a complete reusable learning workflow.')
  await page.getByTestId('save-idea').click()
  await expect(page.getByText('Idea added')).toBeVisible()

  const card = page.locator('.idea-card').filter({ hasText: title })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: 'Generate video' }).click()
  await expect(page).toHaveURL(/\/productions\/[a-z]+_/)

  const approve = page.getByTestId('approve-video')
  await expect(approve).toBeVisible({ timeout: 60_000 })
  const video = page.getByTestId('video-preview')
  await expect(video).toBeVisible()
  await expect.poll(async () => video.evaluate((node: HTMLVideoElement) => node.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1)

  await approve.click()
  const publicationLink = page.getByRole('link', { name: /Prepare publication/ })
  await expect(publicationLink).toBeVisible()
  await publicationLink.click()
  await expect(page.getByRole('heading', { name: 'Publish composer' })).toBeVisible()

  await page.getByTestId('prepare-publication').click()
  await expect(page.getByText('Ready to commit')).toBeVisible()
  await page.getByTestId('confirm-publication').click()
  await expect(page.getByText('Publication committed')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'published' }).first()).toBeVisible()
})

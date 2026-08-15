import { expect, test } from '@playwright/test'
import { registerThroughUi } from './helpers'

const referencePng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
)

test('uploads a reusable character and starts native-audio UGC from an idea', async ({ page }) => {
  await registerThroughUi(page, 'Native UGC')
  await page.goto('/characters')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  const upload = page.getByTestId('character-upload-form')
  await upload.getByLabel('Name').fill('Reusable creator')
  await upload.getByLabel('Description').fill('Adult education creator in casual neutral clothing')
  await upload.getByLabel('Reference image').setInputFiles({
    name: 'creator.png',
    mimeType: 'image/png',
    buffer: referencePng,
  })
  await upload.getByLabel(/I own this image/).check()
  await upload.getByLabel(/Every identifiable person is an adult/).check()
  await upload.getByRole('button', { name: 'Save character' }).click()
  await expect(page.getByText('Character saved')).toBeVisible()
  const characterCard = page.locator('.character-card').filter({ hasText: 'Reusable creator' })
  await expect(characterCard).toBeVisible()
  await expect(characterCard.getByText('Uploaded · rights confirmed')).toBeVisible()

  const generated = page.getByTestId('character-generate-form')
  await generated.getByLabel('Name').fill('Synthetic creator')
  await generated.getByLabel('Creator brief').fill('Warm adult course creator in a quiet home office')
  await generated.getByTestId('generate-character').click()
  await expect(page.getByText('Character generation started')).toBeVisible()
  const generatedCard = page.locator('.character-card').filter({ hasText: 'Synthetic creator' })
  await expect(generatedCard).toContainText('Synthetic · deterministic-test-fixture', { timeout: 15_000 })

  await page.goto('/ideas')
  await page.getByTestId('new-idea').click()
  const title = `Native UGC workflow ${Date.now()}`
  await page.getByTestId('idea-title').fill(title)
  await page.getByLabel('Opening hook').fill('Stop losing hours to one-off content production.')
  await page.getByLabel('Primary audience').fill('Course creators')
  await page.getByLabel('Visual style').selectOption('ugc_native_audio')
  await expect(page.getByText(/generates synchronized direct speech/)).toBeVisible()
  await page.getByLabel('Reusable character').selectOption({ label: 'Reusable creator' })
  await page.getByTestId('save-idea').click()
  await expect(page.getByText('Idea added')).toBeVisible()

  const card = page.locator('.idea-card').filter({ hasText: title })
  await expect(card.getByText('ugc native audio')).toBeVisible()
  const generationResponse = page.waitForResponse(response => (
    response.url().includes('/generation-jobs')
    && response.request().method() === 'POST'
    && response.status() === 202
  ))
  await card.getByRole('button', { name: 'Generate video' }).click()
  await generationResponse
  await expect(page).toHaveURL(/\/productions\/[a-z]+_/)
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await expect(page.getByText(/ugc native audio · Veo native speech/)).toBeVisible({ timeout: 30_000 })
})

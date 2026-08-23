import { expect, test } from '@playwright/test'
import { creditTestBalance, registerThroughUi } from './helpers'

test('research keeps action candidates focused and exposes created and hidden history', async ({ page }) => {
  const account = await registerThroughUi(page, 'Research UX')
  await creditTestBalance(page.request, account.email, 1_000)
  await page.goto('/research')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')

  await page.getByTestId('run-research').click()
  await page.getByLabel('Research objective').fill('Find evidence-backed creator education angles for a short social video')
  await page.getByRole('button', { name: 'Start research' }).click()
  await expect(page.getByText('Research completed')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('research-running')).toHaveCount(0)
  await expect(page.getByTestId('research-filters')).toBeVisible()
  await expect(page.getByTestId('research-history')).toContainText('Research history')
  await expect(page.getByTestId('research-history')).toContainText('5 / 5 candidates')
  await expect(page.getByRole('link', { name: 'Configure automatic research' }).first()).toHaveAttribute('href', '/settings?tab=automation')

  const cards = page.locator('.candidate-card')
  await expect(cards.first()).toBeVisible()
  const countBefore = await cards.count()
  expect(countBefore).toBeGreaterThan(0)
  const firstTitle = await cards.first().locator('h3').innerText()
  await page.getByLabel('Search research candidates').fill(firstTitle.slice(0, 12))
  await expect(cards.first()).toContainText(firstTitle)
  await page.getByLabel('Filter minimum opportunity score').selectOption('70')
  await expect(cards.first()).toBeVisible()
  await page.getByLabel('Filter minimum opportunity score').selectOption('')
  await page.getByLabel('Search research candidates').fill('')
  await cards.first().getByRole('button', { name: 'Details' }).click()

  const details = page.getByTestId('candidate-details')
  await expect(details).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Editorial angle' })).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Supported claims' })).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Unresolved questions' })).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Sources' })).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Recommended production' })).toBeVisible()
  await details.getByRole('button', { name: 'Turn into idea' }).click()
  await expect(page).toHaveURL(/\/research$/)
  await expect(details.getByRole('button', { name: 'Open idea' })).toBeVisible()
  await details.getByLabel('Close candidate details').click()
  await expect(cards).toHaveCount(countBefore - 1)

  await page.getByLabel('Filter candidate status').selectOption('idea_created')
  const createdCard = page.locator('.candidate-card').filter({ hasText: firstTitle })
  await expect(createdCard).toBeVisible()
  await expect(createdCard.getByRole('button', { name: 'Open idea' })).toBeVisible()

  await page.getByLabel('Filter candidate status').selectOption('candidate')
  const hiddenTitle = await cards.first().locator('h3').innerText()
  await cards.first().getByRole('button', { name: 'Hide' }).click()
  await expect(details).toHaveCount(0)
  await expect(cards).toHaveCount(countBefore - 2)
  await page.getByLabel('Filter candidate status').selectOption('hidden')
  await expect(page.locator('.candidate-card').filter({ hasText: hiddenTitle })).toBeVisible()

  await page.getByLabel('Filter candidate status').selectOption('idea_created')
  await createdCard.getByRole('button', { name: 'Open idea' }).click()
  await expect(page).toHaveURL(/\/ideas\?idea=/)
})

test('ideas move between kanban columns and settings require explicit edit mode', async ({ page }, testInfo) => {
  const account = await registerThroughUi(page, 'Workflow UX')
  await page.goto('/ideas')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')
  await page.getByTestId('new-idea').click()
  const title = `Movable idea ${Date.now()}`
  await page.getByTestId('idea-title').fill(title)
  await page.getByLabel('Primary audience').fill('Course creators')
  await page.getByTestId('save-idea').click()
  await expect(page.getByText('Idea added')).toBeVisible()

  const card = page.locator('.idea-card').filter({ hasText: title })
  const readyColumn = page.locator('.idea-column').nth(2)
  if (testInfo.project.name.includes('mobile')) {
    await card.getByLabel(`Move idea: ${title}`).selectOption('ready')
  }
  else {
    await card.dragTo(readyColumn)
  }
  await expect(page.getByText('Idea moved')).toBeVisible()
  await expect(readyColumn.locator('.idea-card').filter({ hasText: title })).toBeVisible()

  await page.goto('/app')
  await page.getByRole('link', { name: 'Open monthly budget settings' }).click()
  await expect(page).toHaveURL(/\/settings\?tab=budget/)
  await expect(page.getByRole('heading', { name: 'Budget & limits', exact: true })).toBeVisible()
  await expect(page.getByLabel(/Hard monthly provider-cost guard/)).toBeVisible()

  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'General', exact: true })).toBeVisible()
  await expect(page.getByLabel('Project name')).toHaveCount(0)
  for (const [tab, heading] of [
    ['brand', 'Brand voice'],
    ['automation', 'Automation'],
    ['budget', 'Budget & limits'],
    ['compliance', 'Compliance'],
    ['general', 'General'],
  ] as const) {
    await page.getByTestId(`settings-tab-${tab}`).click()
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  }

  await page.getByTestId('settings-tab-automation').click()
  await page.getByRole('button', { name: 'Edit automation settings' }).click()
  await page.getByLabel('Run idea research automatically').check()
  await page.getByLabel('Research interval, hours').fill('48')
  await page.getByTestId('save-settings').click()
  await expect(page.getByText('Every 48 hours', { exact: true })).toBeVisible()

  await page.getByTestId('settings-tab-general').click()
  await page.getByTestId('edit-settings').click()
  const projectName = page.getByLabel('Project name')
  await expect(projectName).toHaveValue(account.projectName)
  await projectName.fill(`${account.projectName} Updated`)
  await page.getByTestId('save-settings').click()
  await expect(page.getByText('Settings saved')).toBeVisible()
  await expect(page.getByText(`${account.projectName} Updated`, { exact: true })).toBeVisible()
  await expect(page.getByLabel('Project name')).toHaveCount(0)

  await page.goto('/strategy')
  await expect(page.locator('.strategy-score')).toContainText('Confidence')
  await expect(page.locator('.score-ring')).toHaveCount(0)
})

test('library sends a selected video version to the publication composer', async ({ page }) => {
  await registerThroughUi(page, 'Library publish')
  const versionId = `ver_${Date.now()}`
  await page.route(/\/v1\/projects\/[^/]+\/videos(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{
          id: 'vid_library',
          title: 'Library publish test',
          status: 'approved',
          versions: [{
            id: versionId,
            status: 'approved',
            render_url: '/media/test.mp4?org=test&expires=9999999999&sig=x'.padEnd(90, 'x'),
            aspect_ratio: '9:16',
            duration_ms: 15_000,
          }],
        }],
      }),
    })
  })
  await page.locator('a[href="/library"]').evaluate((element: HTMLAnchorElement) => element.click())
  await expect(page).toHaveURL('/library')
  await page.getByRole('link', { name: 'Send video to publication' }).click()
  await expect(page).toHaveURL(new RegExp(`/publishing\\?version=${versionId}`))
  await expect(page.getByRole('heading', { name: 'Publish composer' })).toBeVisible()
  await expect(page.getByLabel('Video version')).toHaveValue(versionId)
})

import { expect, test } from '@playwright/test'
import { creditTestBalance, registerThroughUi } from './helpers'

test('research persists candidates, exposes details and hides rejected cards', async ({ page }) => {
  const account = await registerThroughUi(page, 'Research UX')
  await creditTestBalance(page.request, account.email, 1_000)
  await page.goto('/research')
  await expect(page.locator('.app-shell')).toHaveAttribute('data-hydrated', 'true')

  await page.getByTestId('run-research').click()
  await page.getByLabel('Research objective').fill('Find evidence-backed creator education angles for a short social video')
  await page.getByRole('button', { name: 'Start research' }).click()
  await expect(page.getByText('Research completed')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('research-running')).toHaveCount(0)

  const cards = page.locator('.candidate-card')
  await expect(cards.first()).toBeVisible()
  const countBefore = await cards.count()
  expect(countBefore).toBeGreaterThan(0)
  await cards.first().getByRole('button', { name: 'Details' }).click()

  const details = page.getByTestId('candidate-details')
  await expect(details).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Editorial angle' })).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Supported claims' })).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Unresolved questions' })).toBeVisible()
  await expect(details.getByRole('heading', { name: 'Sources' })).toBeVisible()
  await details.getByRole('button', { name: 'Hide' }).click()
  await expect(details).toHaveCount(0)
  await expect(cards).toHaveCount(countBefore - 1)
})

test('ideas move between kanban columns and settings require explicit edit mode', async ({ page }, testInfo) => {
  const account = await registerThroughUi(page, 'Workflow UX')
  await page.goto('/ideas')
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

  await page.getByTestId('edit-settings').click()
  const projectName = page.getByLabel('Project name')
  await expect(projectName).toHaveValue(account.projectName)
  await projectName.fill(`${account.projectName} Updated`)
  await page.getByTestId('save-settings').click()
  await expect(page.getByText('Settings saved')).toBeVisible()
  await expect(page.getByText(`${account.projectName} Updated`, { exact: true })).toBeVisible()
  await expect(page.getByLabel('Project name')).toHaveCount(0)
})

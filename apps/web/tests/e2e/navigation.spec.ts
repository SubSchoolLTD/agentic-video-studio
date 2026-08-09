import { expect, test } from '@playwright/test'

const pages = [
  ['/', 'Good morning, Maksim'],
  ['/sources', 'Sources'],
  ['/research', 'Research radar'],
  ['/ideas', 'Ideas'],
  ['/calendar', 'Calendar'],
  ['/productions', 'Productions'],
  ['/library', 'Library'],
  ['/publishing', 'Publishing'],
  ['/analytics', 'Analytics'],
  ['/strategy', 'Strategy memory'],
  ['/connections', 'Connections'],
  ['/developer', 'Developer'],
  ['/settings', 'Project settings'],
] as const

test('all product sections render without route errors', async ({ page }) => {
  for (const [path, heading] of pages) {
    const response = await page.goto(path)
    expect(response?.status(), path).toBeLessThan(400)
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  }
})

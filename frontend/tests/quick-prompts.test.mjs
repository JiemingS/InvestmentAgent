import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { after, before, test } from 'node:test'
import { chromium } from 'playwright-core'
import { createServer } from 'vite'

const now = '2026-11-22T16:30:00Z'
const entry = (title, prompt) => ({ id: randomUUID(), title, prompt })
const chat = title => ({ id: randomUUID(), title, updated_at: now, turns: [] })
const tool = { id: 1, tool: 'get_transactions', status: 'ok', at: now, detail: 'One saved transaction.' }
const answer = {
  model: 'gemma4:31b', status: 'complete', completed_at: now, sections: [],
  direct_answer: 'This is the saved answer.', sources: [], warnings: [],
}
let browser, server, origin

before(async () => {
  server = await createServer({ server: { host: '127.0.0.1', port: 0 } })
  await server.listen()
  origin = 'http://127.0.0.1:' + server.httpServer.address().port
  browser = await chromium.launch(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : { channel: 'chrome' })
})

after(async () => {
  await browser?.close()
  await server?.close()
})

async function fixture({ prompts = [], chats = [], waitForSend } = {}, testContext) {
  const context = await browser.newContext({ viewport: { width: 850, height: 820 } })
  testContext.after(() => context.close())
  const page = await context.newPage()
  const sent = []
  let created = 0
  await page.addInitScript(() => sessionStorage.setItem('investment-agent.active-view', 'agent'))
  await page.route('**/api/agent/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    const method = route.request().method()
    const body = route.request().postDataJSON()
    const respond = (json, status = 200) => route.fulfill({ json, status })
    if (pathname === '/api/agent/quick-prompts') {
      if (method === 'GET') return respond(prompts)
      const item = entry(body.title, body.prompt)
      prompts.push(item)
      return respond(item, 201)
    }
    if (pathname.startsWith('/api/agent/quick-prompts/')) {
      const id = pathname.split('/').at(-1)
      if (id === 'order') {
        prompts = body.ids.map(wanted => prompts.find(item => item.id === wanted))
        return respond(prompts)
      }
      const index = prompts.findIndex(item => item.id === id)
      if (method === 'DELETE') {
        prompts.splice(index, 1)
        return route.fulfill({ status: 204 })
      }
      prompts[index] = { ...prompts[index], ...body }
      return respond(prompts[index])
    }
    if (pathname === '/api/agent/conversations') {
      if (method === 'GET') return respond(chats)
      const item = chat('New chat')
      created++
      chats.unshift(item)
      return respond(item, 201)
    }
    const [, , , , id, operation] = pathname.split('/')
    const current = chats.find(item => item.id === id)
    if (!current) return respond({ detail: 'Not found' }, 404)
    if (!operation) return respond(current)
    assert.equal(operation, 'messages')
    sent.push({ conversation: id, ...body })
    await waitForSend
    current.turns.push({
      id: body.id, question: body.question, created_at: now, status: 'complete',
      error: null, activity: [tool], result: answer,
    })
    return route.fulfill({
      contentType: 'application/x-ndjson',
      body: [
        JSON.stringify({ type: 'activity', activity: tool }),
        JSON.stringify({ type: 'result', result: answer }),
      ].join('\n') + '\n',
    })
  })
  await page.goto(origin)
  const quick = page.getByRole('region', { name: 'Quick Prompts' })
  await quick.getByRole('button', { name: 'Manage' }).waitFor()
  return { page, quick, sent, created: () => created }
}

async function visibleTurns(page, count) {
  await page.waitForFunction(expected => document.querySelectorAll('.agent-turn').length === expected, count)
}

test('manage prompts and restore their display order on reload', async t => {
  const { page, quick } = await fixture({}, t)
  await quick.getByRole('button', { name: 'Manage' }).click()
  for (const [title, prompt] of [['Alpha', 'Body A'], ['Beta', 'Body B']]) {
    await quick.getByRole('button', { name: 'Add prompt' }).click()
    await quick.getByLabel('Prompt title').fill(title)
    await quick.getByLabel('Prompt text').fill(prompt)
    await quick.getByRole('button', { name: 'Save prompt' }).click()
    await quick.getByRole('button', { name: title, exact: true }).waitFor()
  }
  await quick.getByRole('button', { name: 'Edit Alpha' }).click()
  await quick.getByLabel('Prompt title').fill('Edited')
  await quick.getByLabel('Prompt text').fill('Edited full body')
  await quick.getByRole('button', { name: 'Save prompt' }).click()
  await quick.getByRole('button', { name: 'Move Beta up' }).click()
  await page.waitForFunction(() => document.querySelector('.quick-prompt-chip')?.textContent === 'Beta')
  await page.reload()
  await quick.getByRole('button', { name: 'Edited', exact: true }).waitFor()
  assert.deepEqual(await quick.locator('.quick-prompt-chip').allTextContents(), ['Beta', 'Edited'])
  await quick.getByRole('button', { name: 'Manage' }).click()
  await quick.getByRole('button', { name: 'Edit Edited' }).click()
  assert.equal(await quick.getByLabel('Prompt text').inputValue(), 'Edited full body')
  page.once('dialog', dialog => dialog.accept())
  await quick.getByRole('button', { name: 'Delete Beta' }).click()
  await quick.getByRole('button', { name: 'Beta', exact: true }).waitFor({ state: 'detached' })
})

test('sends the full prompt in the selected chat without replacing drafts or history', async t => {
  const first = chat('First conversation')
  const second = chat('Second conversation')
  second.turns.push({
    id: randomUUID(), question: 'An earlier question.', created_at: now,
    status: 'complete', activity: [tool], result: answer, error: null,
  })
  const saved = entry('Public update', 'A full public prompt.\nKeep this second line.')
  const { page, quick, sent, created } = await fixture({ prompts: [saved], chats: [first, second] }, t)
  await page.getByRole('button', { name: second.title }).click()
  await page.getByText('An earlier question.', { exact: true }).waitFor()
  await page.getByLabel('Your question').fill('An unsent draft')
  await quick.getByRole('button', { name: saved.title }).click()
  await visibleTurns(page, 2)
  await page.waitForFunction(() => document.querySelectorAll('.agent-direct').length === 2)
  assert.equal(sent.length, 1)
  assert.equal(sent[0].conversation, second.id)
  assert.equal(sent[0].question, saved.prompt)
  assert.equal(created(), 0)
  assert.equal(await page.getByLabel('Your question').inputValue(), 'An unsent draft')
  await page.reload()
  await page.waitForFunction(() => document.querySelectorAll('.agent-direct').length === 2)
  assert.equal(await page.locator('.agent-turn').count(), 2)
  assert.equal(await page.getByText('Tool activity', { exact: true }).count(), 2)
  assert.equal(await page.locator('.agent-question p').last().textContent(), saved.prompt)
})

test('one click creates one conversation and rapid duplicate clicks send once', async t => {
  const saved = entry('Clock', 'What is the time in UTC?')
  let finish
  const waitForSend = new Promise(resolve => { finish = resolve })
  const { page, quick, sent, created } = await fixture({ prompts: [saved], waitForSend }, t)
  try {
    const button = quick.getByRole('button', { name: 'Clock', exact: true })
    await page.waitForFunction(() => !document.querySelector('.quick-prompt-chip')?.disabled)
    await button.evaluate(element => { element.click(); element.click() })
    await page.getByText('Working on the local analysis…', { exact: true }).waitFor()
    assert.equal(await button.isDisabled(), true)
    assert.equal(created(), 1)
    finish()
    await page.getByText(answer.direct_answer, { exact: true }).waitFor()
    assert.equal(sent.length, 1)
    assert.equal(sent[0].question, saved.prompt)
    assert.equal(await page.locator('.agent-turn').count(), 1)
  } finally {
    finish()
  }
})

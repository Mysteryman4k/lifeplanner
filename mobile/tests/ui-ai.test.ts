/* The study assistant in the phone app, at phone size in a real browser: turning it on, setting up a provider,
   a streamed reply, a task the assistant adds (with Undo) and an attached PDF read by pdf.js. The provider is
   faked with Playwright, so nothing goes online. Set EUT_UI=1 to run (CI does). */
import type { Server } from 'node:http';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { minimalPdf } from './helpers';

const RUN = !!process.env.EUT_UI;

describe.skipIf(!RUN)('study assistant on the phone', () => {
  let server: Server;
  let base: string;
  let browser: import('playwright').Browser;
  let page: import('playwright').Page;
  const errors: string[] = [];
  const replies: string[] = [];
  const sent: any[] = [];

  const sse = (...events: unknown[]) => events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n';
  const say = (text: string) => sse({ choices: [{ delta: { content: text } }] }, { choices: [], usage: { prompt_tokens: 40, completion_tokens: 20 } });
  const tool = (name: string, args: unknown) => sse({ choices: [{ delta: { tool_calls: [{ index: 0, id: 'c1', function: { name, arguments: JSON.stringify(args) } }] }, finish_reason: 'tool_calls' }] });

  beforeAll(async () => {
    const { serve } = await import('../scripts/serve.mjs' as string);
    server = await serve(0);
    base = `http://127.0.0.1:${(server.address() as any).port}`;
    const { chromium, devices } = await import('playwright');
    browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
    const context = await browser.newContext({ ...devices['Pixel 7'], timezoneId: 'Australia/Melbourne', locale: 'en-AU' });
    // A fake OpenAI: its model list, and streamed replies in the order the test queues them
    await context.route('https://api.openai.com/**', async route => {
      const url = new URL(route.request().url());
      const cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*' };
      if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
      if (url.pathname === '/v1/models') return route.fulfill({ status: 200, headers: cors, json: { data: [{ id: 'gpt-5' }, { id: 'gpt-5-mini' }] } });
      sent.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, headers: { ...cors, 'content-type': 'text/event-stream' }, body: replies.shift() ?? say('ok') });
    });
    page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  }, 60000);

  afterAll(async () => {
    await browser?.close();
    server?.close();
  });

  it('is off until turned on, then set up with a key kept out of the page', async () => {
    await page.goto(`${base}/#/settings`);
    await page.waitForSelector('#aiCard [data-action=ai-start]');
    expect(await page.locator('#tabbar').innerText()).not.toContain('Study');
    await page.click('#aiCard [data-action=ai-start]');
    await page.click('[data-action=ai-terms-next]');
    const ticks = page.locator('.ai-tick');
    for (let i = 0; i < 3; i++) await ticks.nth(i).check();
    await page.click('#aiAgree');
    await page.waitForSelector('#aiCard [data-action=toggle-ai-assistant]');
    expect(await page.locator('[data-action=toggle-ai-code]').count()).toBe(0);           // no code workspace on a phone
    expect(await page.locator('[data-action=ai-provider][data-id=ollama]').count()).toBe(0);
    await page.click('[data-action=ai-provider][data-id=openai]');
    await page.fill('#aiKey', 'sk-test-abcd9876');
    await page.click('[data-action=ai-save-key]');
    await page.waitForSelector("text=Saved in this phone's secure storage (…9876)");
    expect(await page.content()).not.toContain('sk-test-abcd9876');
    await page.click('[data-action=ai-test]');
    await page.waitForSelector('#aiTestResult.ai-ok');
    expect(await page.inputValue('#aiModel')).toBe('gpt-5-mini');
    expect((await page.locator('#tabbar .tab').allInnerTexts()).map(t => t.trim())).toEqual(['Today', 'Tasks', 'Calendar', 'Study', 'More']);
    expect(errors).toEqual([]);
  });

  it('streams a reply safely and adds a task the student can undo', async () => {
    replies.push(say('## Recursion\nA function that **calls itself**. <script>window.hacked=1</script>'));
    await page.click('#tabbar .tab >> text=Study');
    await page.waitForSelector('#chatInput');
    await page.fill('#chatInput', 'What is recursion?');
    await page.press('#chatInput', 'Enter');                   // the phone keyboard's return: a new line, not send
    expect(await page.locator('.chat-msg.user').count()).toBe(0);
    await page.click('#chatForm [type=submit]');
    await page.waitForSelector('.chat-msg.ai .chat-tools');
    expect(await page.locator('.chat-msg.ai strong').innerText()).toBe('calls itself');
    expect(await page.evaluate(() => (window as any).hacked)).toBeUndefined();
    expect(sent[0].messages[0].content).toContain('not an answer writer');

    replies.push(tool('add_task', { title: 'Draft intro', due_date: '2026-11-03' }), say('Added it.'));
    await page.fill('#chatInput', 'Add a task to draft my intro');
    await page.click('#chatForm [type=submit]');
    await page.locator('.chat-card.ok', { hasText: 'Draft intro' }).waitFor();
    await page.waitForFunction("state.tasks.some(t => t.title === 'Draft intro')");
    await page.click('[data-action=chat-undo]');
    await page.locator('.chat-card.muted-card', { hasText: 'Undone' }).waitFor();
    expect(await page.evaluate("state.tasks.some(t => t.title === 'Draft intro')")).toBe(false);
    expect(errors).toEqual([]);
  });

  it('reads an attached PDF on the phone and sends its text with the question', async () => {
    await page.click('[data-action=chat-new] >> nth=0');
    await page.setInputFiles('#chatFile', { name: 'Week 3.pdf', mimeType: 'application/pdf', buffer: Buffer.from(minimalPdf(['Stacks are LIFO', 'Queues are FIFO'])) });
    await page.waitForSelector('.chat-file-head >> text=Week 3.pdf', { timeout: 8000 }).catch(async e => {
      console.log('PAGE ERRORS', errors, await page.locator('#toast').innerText());
      throw e;
    });
    replies.push(say('Page 2 covers queues.'));
    await page.fill('#chatInput', 'What is on page 2?');
    await page.click('#chatForm [type=submit]');
    await page.waitForSelector('.chat-msg.ai >> text=Page 2 covers queues.');
    const system: string = sent.at(-1).messages[0].content;
    expect(system).toContain('Stacks are LIFO');
    expect(system).toContain('Queues are FIFO');
    expect(errors).toEqual([]);
  });
});

/* The phone app in a real browser at phone size: the built www/ (npm run build) with its own backend, as it
   runs on a phone, minus the native plugins. Set EUT_UI=1 to run (CI does); it needs Chromium for Playwright. */
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Server } from 'node:http';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { d } from './helpers';

const RUN = !!process.env.EUT_UI;

describe.skipIf(!RUN)('phone app in a browser', () => {
  let server: Server;
  let base: string;
  let browser: import('playwright').Browser;
  let context: import('playwright').BrowserContext;
  let page: import('playwright').Page;
  const errors: string[] = [];

  beforeAll(async () => {
    const { serve } = await import('../scripts/serve.mjs' as string);
    server = await serve(0);
    base = `http://127.0.0.1:${(server.address() as any).port}`;
    const { chromium, devices } = await import('playwright');
    browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
    context = await browser.newContext({ ...devices['Pixel 7'], timezoneId: 'Australia/Melbourne', locale: 'en-AU' });
    page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  }, 60000);

  afterAll(async () => {
    await browser?.close();
    server?.close();
  });

  const go = async (route: string) => {
    await page.goto(`${base}/#/${route}`);
    await page.waitForSelector('#content > *');
  };

  it('opens on Today with the phone tabs', async () => {
    await go('today');
    expect((await page.innerText('#pageTitle')).trim()).toMatch(/^Good (morning|afternoon|evening)$/);
    const tabs = await page.locator('#tabbar .tab').allInnerTexts();
    expect(tabs.map(t => t.trim())).toEqual(['Today', 'Tasks', 'Calendar', 'Money', 'More']);
    expect(await page.locator('.sidebar').isVisible()).toBe(false);
    expect(errors).toEqual([]);
  });

  for (const route of ['tasks', 'calendar', 'subjects', 'jobs', 'money', 'more', 'settings']) {
    it(`shows ${route}`, async () => {
      await go(route);
      expect((await page.innerText('#pageTitle')).trim()).not.toBe('');
      expect(errors).toEqual([]);
    });
  }

  it('adds a task in the sheet and completes it', async () => {
    await go('tasks');
    await page.click('[data-action=new-task] >> nth=0');
    await page.fill('[name=title]', '<b>Phone</b> task');
    await page.fill('[name=due_date]', d(1));
    await page.click('#drawerFoot [type=submit]');
    await page.waitForSelector('text=<b>Phone</b> task');          // shown as text, not HTML
    await page.click('.task .check >> nth=0');
    await page.waitForFunction(() => document.querySelectorAll('.task').length === 0);
    expect(errors).toEqual([]);
  });

  it('keeps what you add after the app is closed and opened again', async () => {
    await go('jobs');
    await page.click('[data-action=new-job] >> nth=0');
    await page.fill('[name=company]', 'Atlassian');
    await page.fill('[name=role]', 'Graduate Engineer');
    await page.click('#drawerFoot [type=submit]');
    await page.waitForSelector('.job >> text=Atlassian');
    await page.reload();
    await page.waitForSelector('.job >> text=Atlassian');
    expect(errors).toEqual([]);
  });

  it('lists Jobs, Subjects and Settings under More, and More lights up there', async () => {
    await go('more');
    const rows = (await page.locator('.more-row').allInnerTexts()).map(t => t.split('\n')[0].trim());
    expect(rows).toEqual(expect.arrayContaining(['Subjects', 'Jobs', 'Settings']));
    expect(rows).not.toContain('Money');                        // it's a tab
    await page.click('.more-row >> text=Jobs');
    await page.waitForSelector('#pageTitle >> text=Job applications');
    expect((await page.innerText('#tabbar .tab.active')).trim()).toBe('More');
    expect(errors).toEqual([]);
  });

  it('shows phone settings: no Windows options, backups go to the share sheet', async () => {
    await go('settings');
    const text = await page.innerText('#content');
    expect(text).toContain('Saved on this phone');
    expect(text).not.toContain('Start with Windows');
    expect(text).not.toContain('Intro animation');
    expect(text).not.toContain('Check for updates automatically');
    const download = page.waitForEvent('download');           // the preview's stand-in for the share sheet
    await page.click('[data-action=export]');
    const file = await download;
    const backup = JSON.parse(readFileSync((await file.path())!, 'utf8'));
    expect(backup.app).toBe('EasyUniTrack');
    expect(backup.job_applications.map((j: any) => j.company)).toContain('Atlassian');
    expect(errors).toEqual([]);
  });

  it('restores a backup made by the desktop app', async () => {
    const backup = {
      app: 'EasyUniTrack', version: '3.6.0', exported_at: '2026-10-01 09:00',
      subjects: [{ id: 1, name: 'COMP2001 Data Structures', color: '#3B6EA8', icon: '' }],
      tasks: [{ id: 1, title: 'Graph algorithms lab', due_date: d(2), subject_id: 1, status: 'not_started', priority: 'high' }],
      job_applications: [], transactions: [], budgets: [], settings: [{ key: 'appearance', value: '{"theme":"ocean","font":"system","mode":"light"}' }],
    };
    const dir = mkdtempSync(join(tmpdir(), 'eut-ui-'));
    const path = join(dir, 'desktop-backup.json');
    writeFileSync(path, JSON.stringify(backup));
    await go('settings');
    page.once('dialog', dlg => dlg.accept());
    await page.setInputFiles('#importFile', path);
    await page.click('#confirmYes');
    await page.waitForSelector('#toast.show >> text=Backup restored');
    await go('tasks');
    await page.waitForSelector('text=Graph algorithms lab');
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('ocean');
    expect(errors).toEqual([]);
  });

  it('works offline once loaded (no server calls leave the phone)', async () => {
    await go('today');
    const outside: string[] = [];
    const failed: string[] = [];
    page.on('request', r => { if (!r.url().startsWith(base)) outside.push(r.url()); });
    page.on('requestfailed', r => failed.push(new URL(r.url()).pathname));
    await context.setOffline(true);
    await page.evaluate(() => { location.hash = '#/money'; });       // within the app: its files are on the phone
    await page.waitForSelector('#pageTitle >> text=Money');
    await page.click('[data-action=new-tx] >> nth=0');
    await page.fill('[name=amount]', '12.50');
    await page.fill('[name=description]', 'Coffee');
    await page.click('#drawerFoot [type=submit]');
    await page.waitForSelector('text=Coffee');
    await context.setOffline(false);
    expect(outside).toEqual([]);
    // Only the browser tab's icon (the preview server's, which a phone doesn't have) may fail to load
    expect(failed.filter(p => p !== '/static/icon-32.png')).toEqual([]);
    expect(errors.filter(e => !e.includes('ERR_INTERNET_DISCONNECTED'))).toEqual([]);
  });
});

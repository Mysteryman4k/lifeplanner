/* The phone's own features through Capacitor plugins: notifications, files, sharing and the key vault. */
import { Capacitor } from '@capacitor/core';
import { Directory, Encoding, Filesystem } from '@capacitor/filesystem';
import { LocalNotifications } from '@capacitor/local-notifications';
import { Share } from '@capacitor/share';
import type { Platform } from '../api/context';

const BACKUPS = 'backups';

export function region(): string {
  const lang = navigator.languages?.[0] || navigator.language || '';
  try {
    return new Intl.Locale(lang).maximize().region || '';
  } catch {
    return lang.split('-')[1] || '';
  }
}

async function allowedToNotify(ask: boolean): Promise<boolean> {
  let perm = await LocalNotifications.checkPermissions();
  if (perm.display === 'prompt' || perm.display === 'prompt-with-rationale') {
    if (!ask) return false;
    perm = await LocalNotifications.requestPermissions();
  }
  return perm.display === 'granted';
}

let channelMade = false;
async function channel() {
  if (channelMade || Capacitor.getPlatform() !== 'android') return;
  await LocalNotifications.createChannel({
    id: 'reminders', name: 'Daily reminder', description: "What's due today, what's overdue and job follow-ups",
    importance: 4, visibility: 1,
  });
  channelMade = true;
}

export const notifications = {
  allowed: allowedToNotify,

  async show(title: string, body: string): Promise<boolean> {
    if (!(await allowedToNotify(true))) return false;
    await channel();
    await LocalNotifications.schedule({
      notifications: [{ id: 999, title, body, largeBody: body, channelId: 'reminders', smallIcon: 'ic_stat_notify' }],
    });
    return true;
  },

  /** Replace the scheduled daily reminders with these. */
  async replace(ids: number[], planned: { id: number; at: Date; title: string; body: string }[], ask: boolean) {
    const pending = (await LocalNotifications.getPending()).notifications.filter(n => ids.includes(n.id));
    if (pending.length) await LocalNotifications.cancel({ notifications: pending.map(n => ({ id: n.id })) });
    if (!planned.length || !(await allowedToNotify(ask))) return;
    await channel();
    await LocalNotifications.schedule({
      notifications: planned.map(p => ({
        id: p.id, title: p.title, body: p.body, largeBody: p.body, channelId: 'reminders', smallIcon: 'ic_stat_notify',
        schedule: { at: p.at, allowWhileIdle: true }, isExactNotification: false,
      })),
    });
  },
};

export const nativeBackups: Platform['backups'] = {
  folder: 'App storage › backups',
  async write(name, text) {
    await Filesystem.writeFile({ path: `${BACKUPS}/${name}`, data: text, directory: Directory.Data, encoding: Encoding.UTF8, recursive: true });
  },
  async list() {
    try {
      return (await Filesystem.readdir({ path: BACKUPS, directory: Directory.Data })).files.map(f => f.name);
    } catch {
      return [];                                    // no folder yet
    }
  },
  async remove(name) {
    await Filesystem.deleteFile({ path: `${BACKUPS}/${name}`, directory: Directory.Data });
  },
};

/** Hand a file to the share sheet (save to Files or Drive, email it, …): the phone's "download". */
export async function shareFile(name: string, text: string) {
  const { uri } = await Filesystem.writeFile({ path: name, data: text, directory: Directory.Cache, encoding: Encoding.UTF8 });
  try {
    await Share.share({ title: name, files: [uri], dialogTitle: 'Save or send your backup' });
    return true;
  } catch (e) {
    if (/cancel/i.test(String((e as Error)?.message))) return false;     // closed the share sheet
    throw e;
  }
}

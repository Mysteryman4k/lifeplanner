/* The browser preview (npm run preview, and the phone-size browser tests): the same app in a normal
   browser, with its database kept in IndexedDB. Nothing here runs on a phone. */
import type { Platform } from '../api/context';

const DB = 'easyunitrack-preview';

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore('files');
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function store<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('files', mode);
    const req = fn(tx.objectStore('files'));
    tx.oncomplete = () => resolve(req.result);
    tx.onerror = () => reject(tx.error);
  });
}

export const webFiles = {
  read: (name: string) => store<any>('readonly', s => s.get(name)),
  write: (name: string, value: unknown) => store('readwrite', s => s.put(value, name)),
  remove: (name: string) => store('readwrite', s => s.delete(name)),
  keys: async () => (await store<IDBValidKey[]>('readonly', s => s.getAllKeys())).map(String),
};

export const webBackups: Platform['backups'] = {
  folder: 'Browser storage › backups',
  write: (name, text) => webFiles.write(`backups/${name}`, text).then(() => undefined),
  list: async () => (await webFiles.keys()).filter(k => k.startsWith('backups/')).map(k => k.slice(8)),
  remove: name => webFiles.remove(`backups/${name}`).then(() => undefined),
};

export async function webNotify(title: string, body: string) {
  if (!('Notification' in window)) return false;
  if (Notification.permission === 'default') await Notification.requestPermission();
  if (Notification.permission !== 'granted') return false;
  new Notification(title, { body, icon: '/static/icon-192.png' });
  return true;
}

/** Keys in the preview are kept for this browser tab only: it's for trying the app out, not for real keys. */
const vault = new Map<string, string>();
export const webSecrets: Platform['secrets'] = {
  get: async k => vault.get(k) ?? null,
  set: async (k, v) => { vault.set(k, v); },
  remove: async k => { vault.delete(k); },
};

export function downloadFile(name: string, text: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  return true;
}

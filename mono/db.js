// IndexedDB ラッパー。
// アイテムは1ストアで管理し、status ('owned' | 'released') で現役/手放し済みを区別する。

const DB_NAME = 'mono-inventory';
const DB_VERSION = 1;
const STORE = 'items';

let dbPromise = null;

function openDB() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: 'id' });
        store.createIndex('status', 'status');
        store.createIndex('category', 'category');
        store.createIndex('acquiredAt', 'acquiredAt');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function tx(db, mode) {
  return db.transaction(STORE, mode).objectStore(STORE);
}

function request(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function putItem(item) {
  const db = await openDB();
  await request(tx(db, 'readwrite').put(item));
  return item;
}

export async function getItem(id) {
  const db = await openDB();
  return request(tx(db, 'readonly').get(id));
}

export async function deleteItem(id) {
  const db = await openDB();
  return request(tx(db, 'readwrite').delete(id));
}

export async function getAllItems() {
  const db = await openDB();
  return request(tx(db, 'readonly').getAll());
}

export function newId() {
  return crypto.randomUUID ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

// カテゴリのマスタ一覧管理。
// localStorage('mono.categories') にJSON配列で保存し、未設定・壊れている場合は
// DEFAULT_CATEGORIES のコピーを返す。

const STORAGE_KEY = 'mono.categories';

export const DEFAULT_CATEGORIES = [
  '衣類', '靴', 'バッグ', '本', 'ガジェット', 'キッチン', '日用品', '家具', '趣味', '美容', '書類', 'その他',
];

/**
 * カテゴリのマスタ一覧を取得する。
 * @returns {string[]}
 */
export function getCategories() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return [...DEFAULT_CATEGORIES];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...DEFAULT_CATEGORIES];
    const cleaned = parsed.map((c) => String(c).trim()).filter(Boolean);
    return cleaned.length ? cleaned : [...DEFAULT_CATEGORIES];
  } catch {
    return [...DEFAULT_CATEGORIES];
  }
}

/**
 * カテゴリのマスタ一覧を保存する。
 * 前後の空白を除去し、空要素・重複を取り除いてから保存する。
 * @param {string[]} list
 */
export function setCategories(list) {
  const seen = new Set();
  const cleaned = [];
  (list || []).forEach((c) => {
    const t = String(c ?? '').trim();
    if (!t || seen.has(t)) return;
    seen.add(t);
    cleaned.push(t);
  });
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cleaned));
  return cleaned;
}

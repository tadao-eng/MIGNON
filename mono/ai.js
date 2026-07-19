// 画像・バーコードからの品目情報推定。
//
// suggestItemInfo() はブラウザ内AI(TensorFlow.js + MobileNet)で画像分類を行い、
// ImageNetの英語クラス名を ai-labels.js の LABEL_RULES でアプリのカテゴリ/日本語品名に
// マッピングする。サーバには一切送信されず、モデルは写真が選ばれた時点で初めて
// CDN から遅延ロードされる(初期表示を重くしないため)。
// より高精度な判定に差し替えたい場合(例: Claude API 等の Vision 系API)は、
// この suggestItemInfo() の中身を差し替えるだけでよい(app.js は戻り値
// {name, category} | null しか見ない)。
import { LABEL_RULES } from './ai-labels.js';

const TFJS_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js';
const MOBILENET_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow-models/mobilenet@2.1.1/dist/mobilenet.min.js';
const LOAD_TIMEOUT_MS = 20000;
const MIN_PROBABILITY = 0.25;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`スクリプトを取得できませんでした: ${src}`));
    document.head.appendChild(s);
  });
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('タイムアウトしました')), ms);
    promise.then(
      (v) => { clearTimeout(timer); resolve(v); },
      (e) => { clearTimeout(timer); reject(e); }
    );
  });
}

// モデルのロードは一度だけ行い、以降は同じ Promise を再利用する。
// 失敗した場合は変数を戻して次回呼び出し時に再試行できるようにする。
let modelLoading = null;

async function loadModel() {
  if (!modelLoading) {
    modelLoading = (async () => {
      if (!window.tf) await loadScript(TFJS_URL);
      if (!window.mobilenet) await loadScript(MOBILENET_URL);
      return window.mobilenet.load({ version: 2, alpha: 0.5 });
    })();
    modelLoading.catch(() => { modelLoading = null; });
  }
  return withTimeout(modelLoading, LOAD_TIMEOUT_MS);
}

async function blobToImageSource(blob) {
  try {
    return await createImageBitmap(blob);
  } catch {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(blob);
      img.onload = () => { resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('画像を読み込めませんでした')); };
      img.src = url;
    });
  }
}

function matchLabel(className) {
  const lower = className.toLowerCase();
  for (const rule of LABEL_RULES) {
    if (rule.kw.some((kw) => lower.includes(kw))) return rule;
  }
  return null;
}

/**
 * アプリ起動直後に裏でモデルをロード+ウォームアップしておく。
 * 写真選択時にはすでにロード・コンパイル済みの状態にして、初回判別の待ちをなくす。
 * loadModel() と同じ modelLoading キャッシュを共有するだけで、ロード自体のロジックは変更しない。
 * オフライン・CDN不達など、いかなる失敗でも例外を外に漏らさず静かに諦める。
 */
export async function preloadModel() {
  try {
    const model = await loadModel();
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#888';
    ctx.fillRect(0, 0, 64, 64);
    ctx.fillStyle = '#ccc';
    ctx.fillRect(16, 16, 32, 32);
    await model.classify(canvas, 1);
  } catch {
    // オフライン・CDN不達・タイムアウトなど: 静かに諦める(写真選択時に通常フローで再試行される)
  }
}

/**
 * 写真から品目名・カテゴリを推定する(ブラウザ内AI・端末内完結)。
 * オフライン・CDN不達・タイムアウトなど、いかなる失敗でも null を返し
 * 手動入力にフォールバックする。
 * @param {Blob} photoBlob 撮影画像
 * @returns {Promise<{name?: string, category?: string} | null>}
 */
export async function suggestItemInfo(photoBlob) {
  try {
    const model = await loadModel();
    const imgSource = await blobToImageSource(photoBlob);
    const predictions = await model.classify(imgSource, 3);
    if (imgSource instanceof HTMLImageElement) URL.revokeObjectURL(imgSource.src);
    else if (typeof imgSource.close === 'function') imgSource.close();

    for (const pred of predictions || []) {
      if (pred.probability < MIN_PROBABILITY) continue;
      const rule = matchLabel(pred.className);
      if (rule) return { name: rule.name, category: rule.category };
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * バーコード(JAN/EAN)から商品名を引く。
 * Open Food Facts の公開APIを使用(無料・CORS対応)。食品以外はヒットしないことが
 * 多いので、失敗・未ヒット時は null を返して手動入力にフォールバックする。
 * @param {string} code
 * @returns {Promise<{name?: string, category?: string} | null>}
 */
export async function lookupBarcode(code) {
  if (!navigator.onLine) return null;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    const res = await fetch(
      `https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(code)}.json?fields=product_name,product_name_ja,brands`,
      { signal: ctrl.signal }
    );
    clearTimeout(timer);
    if (!res.ok) return null;
    const data = await res.json();
    const p = data.product;
    if (!p) return null;
    const name = p.product_name_ja || p.product_name || '';
    if (!name) return null;
    return { name: p.brands ? `${name}(${p.brands})` : name };
  } catch {
    return null;
  }
}

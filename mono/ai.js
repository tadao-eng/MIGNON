// 画像・バーコードからの品目情報推定。
//
// suggestItemInfo() / analyzePhoto() はどちらも共通の classifyPhoto()(ブラウザ内AI・
// TensorFlow.js + MobileNet)で画像分類を行い、ImageNetの英語クラス名を ai-labels.js の
// LABEL_RULES でアプリのカテゴリ/日本語品名にマッピングする。サーバには一切送信されず、
// モデルは写真が選ばれた時点で初めて CDN から遅延ロードされる(初期表示を重くしないため)。
// suggestItemInfo() は写真選択時の自動判別用(結果 {name, category} | null のみ、失敗理由は
// 区別しない)。analyzePhoto() は手動「AI分析」ボタン用(モデル起因の失敗とルール未ヒットを
// status で区別して返す)。
// より高精度な判定に差し替えたい場合(例: Claude API 等の Vision 系API)は、
// classifyPhoto() の中身を差し替えるだけでよい(app.js は各関数の戻り値の形しか見ない)。
import { LABEL_RULES } from './ai-labels.js';

const TFJS_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js';
const MOBILENET_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow-models/mobilenet@2.1.1/dist/mobilenet.min.js';
const LOAD_TIMEOUT_MS = 20000;
const MIN_PROBABILITY = 0.25;
// 手動「AI分析」ボタン用のしきい値。ユーザーが明示的に操作しているため、
// 自動判別(MIN_PROBABILITY)より緩めにして「近い候補」も拾えるようにする。
const MIN_PROBABILITY_MANUAL = 0.15;

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
 * モデルのロードから画像分類までを行う共通の推論処理。
 * モデルロード・画像デコード・推論のいずれかが失敗した場合はそのまま例外を投げる
 * (呼び出し側でオフライン・CDN不達・タイムアウト等の「モデル起因の失敗」として扱う)。
 * @param {Blob} photoBlob
 * @returns {Promise<Array<{className: string, probability: number}>>} 確率降順の予測配列
 */
async function classifyPhoto(photoBlob) {
  const model = await loadModel();
  const imgSource = await blobToImageSource(photoBlob);
  const predictions = await model.classify(imgSource, 5);
  if (imgSource instanceof HTMLImageElement) URL.revokeObjectURL(imgSource.src);
  else if (typeof imgSource.close === 'function') imgSource.close();
  return predictions;
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
    const predictions = await classifyPhoto(photoBlob);
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
 * 写真から品目名・カテゴリを推定する(手動「AI分析」ボタン用)。
 * suggestItemInfo() と異なり、失敗理由(モデルのロード/推論失敗 か、判別はできたが
 * ルール表に該当が無いか)を区別して返す。ユーザーが明示的に操作しているため
 * しきい値も MIN_PROBABILITY_MANUAL(0.15)と緩めにしている。
 * この関数自体は例外を投げない。
 * @param {Blob} photoBlob 撮影画像
 * @returns {Promise<
 *   | { status: 'ok', name?: string, category?: string, top: { className: string, probability: number } }
 *   | { status: 'no-match', top: { className: string, probability: number } | null }
 *   | { status: 'model-error' }
 * >}
 */
export async function analyzePhoto(photoBlob) {
  let predictions;
  try {
    predictions = await classifyPhoto(photoBlob);
  } catch {
    return { status: 'model-error' };
  }

  for (const pred of predictions || []) {
    if (pred.probability < MIN_PROBABILITY_MANUAL) continue;
    const rule = matchLabel(pred.className);
    if (rule) {
      return {
        status: 'ok',
        name: rule.name,
        category: rule.category,
        top: { className: pred.className, probability: pred.probability },
      };
    }
  }

  const top = predictions && predictions.length
    ? { className: predictions[0].className, probability: predictions[0].probability }
    : null;
  return { status: 'no-match', top };
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

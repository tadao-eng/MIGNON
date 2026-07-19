// 画像・バーコードからの品目情報推定。
//
// 判別方式には優先順位があり、上から順に使える設定があればそれを使う:
//   1. 中継サーバ(Cloudflare Worker) — proxyUrl() が設定されていれば classifyViaProxy() を使う。
//      Gemini APIキーはユーザー自身がデプロイした Worker 側にのみ保存され、ブラウザには
//      一切残らない(詳細は mono/proxy/README.md)。
//   2. Gemini API 直接呼び出し — geminiKey() が設定されていれば classifyWithGemini() を使う。
//      APIキーがブラウザ(localStorage)に保存される簡易方式。
//   3. ブラウザ内AI(TensorFlow.js + MobileNet) — 上記どちらも未設定、または失敗時のフォールバック。
//      classifyPhoto() で画像分類を行い、ImageNetの英語クラス名を ai-labels.js の LABEL_RULES で
//      アプリのカテゴリ/日本語品名にマッピングする。この経路はサーバには一切送信されず、モデルは
//      写真が選ばれた時点で初めて CDN から遅延ロードされる(初期表示を重くしないため)。
// suggestItemInfo() は写真選択時の自動判別用(結果 {name, category} | null のみ、失敗理由は
// 区別しない)。analyzePhoto() は手動「AI分析」ボタン用(中継サーバ・Gemini起因の失敗と
// モデル起因の失敗、ルール未ヒットを status で区別して返す)。
import { LABEL_RULES } from './ai-labels.js';
import { getCategories } from './categories.js';

const TFJS_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js';
const MOBILENET_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow-models/mobilenet@2.1.1/dist/mobilenet.min.js';
const LOAD_TIMEOUT_MS = 20000;
const MIN_PROBABILITY = 0.25;
// 手動「AI分析」ボタン用のしきい値。ユーザーが明示的に操作しているため、
// 自動判別(MIN_PROBABILITY)より緩めにして「近い候補」も拾えるようにする。
const MIN_PROBABILITY_MANUAL = 0.15;

// ---------- Gemini API(ユーザー自身のAPIキーを使用する高精度判別) ----------

const GEMINI_MODEL = 'gemini-2.5-flash';
const GEMINI_TIMEOUT_MS = 20000;

// ユーザーが編集したカテゴリのマスタ一覧を、リクエスト組み立て時に毎回埋め込む
// (呼び出しごとに評価することで、カテゴリ編集後の判別に即座に反映される)。
function geminiPrompt() {
  return 'この写真に写っている主要な持ち物1点を判定してください。JSONのみで回答: ' +
    `{"name": 日本語の簡潔な品名(最大20文字), "category": 次のリストから最も近い1つ ${JSON.stringify(getCategories())}}。` +
    '何が写っているか判定できない場合は {"name": null, "category": null}';
}

function geminiKey() {
  return (localStorage.getItem('mono.geminiKey') || '').trim();
}

function proxyUrl() {
  return (localStorage.getItem('mono.proxyUrl') || '').trim();
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',').pop());
    reader.onerror = () => reject(new Error('画像を読み込めませんでした'));
    reader.readAsDataURL(blob);
  });
}

/**
 * ユーザー自身の Gemini APIキーで写真を判別する(高精度・要ネットワーク)。
 * @param {Blob} photoBlob
 * @returns {Promise<{ result: {name: string|null, category: string|null} | null } | { error: 'auth' }>}
 *   認証エラー(400/401/403、無効なキー相当)以外の失敗は例外を投げる。
 */
async function classifyWithGemini(photoBlob) {
  const key = geminiKey();
  const base64 = await blobToBase64(photoBlob);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), GEMINI_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`,
      {
        method: 'POST',
        headers: { 'x-goog-api-key': key, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{
            parts: [
              { inline_data: { mime_type: photoBlob.type || 'image/jpeg', data: base64 } },
              { text: geminiPrompt() },
            ],
          }],
          generationConfig: { response_mime_type: 'application/json' },
        }),
        signal: ctrl.signal,
      }
    );
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    if (res.status === 400 || res.status === 401 || res.status === 403) {
      return { error: 'auth' };
    }
    throw new Error(`Gemini API エラー: ${res.status}`);
  }

  const data = await res.json();
  const text = (data?.candidates?.[0]?.content?.parts || [])
    .map((p) => p.text || '')
    .join('');
  const cleaned = text.trim().replace(/^```json\s*/i, '').replace(/^```\s*/, '').replace(/```\s*$/, '').trim();
  const parsed = JSON.parse(cleaned);
  if (!parsed.name && !parsed.category) return { result: null };
  return { result: { name: parsed.name || null, category: parsed.category || null } };
}

const PROXY_TIMEOUT_MS = 25000;

/**
 * ユーザーが設置した中継サーバ(Cloudflare Worker)経由で写真を判別する。
 * Gemini APIキーは端末に置かず、Worker側にのみ保存される構成のための経路。
 * @param {Blob} photoBlob
 * @returns {Promise<{ result: {name: string|null, category: string|null} | null } | { error: 'proxy-config' | 'quota' }>}
 *   中継サーバの設定不備(403/400/no-key相当の500)は 'proxy-config'、利用上限超過は 'quota' として
 *   返す。それ以外の失敗(通信エラー・タイムアウト・想定外のレスポンス等)は例外を投げる。
 */
async function classifyViaProxy(photoBlob) {
  const url = proxyUrl();
  const base64 = await blobToBase64(photoBlob);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROXY_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image: base64,
        mime: photoBlob.type || 'image/jpeg',
        categories: getCategories(),
      }),
      signal: ctrl.signal,
    });
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    if (res.status === 429) return { error: 'quota' };
    if (res.status === 403 || res.status === 400 || res.status === 500) return { error: 'proxy-config' };
    throw new Error(`中継サーバエラー: ${res.status}`);
  }

  const data = await res.json();
  return { result: data.result ?? null };
}

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
  if (geminiKey() || proxyUrl()) return; // 中継サーバ/Gemini使用時はMobileNetの先読みをスキップ(フォールバック時は遅延ロードで賄う)
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
 * 写真から品目名・カテゴリを推定する。
 * 中継サーバURL・Gemini APIキーの順に設定を確認し、設定があればそちらを試す(高精度)。
 * 設定不備・認証エラー・通信失敗など、いかなる問題が起きても従来のブラウザ内AI(MobileNet)
 * 経路に静かにフォールバックする。オフライン・CDN不達・タイムアウトなど、いかなる失敗でも
 * null を返し手動入力にフォールバックする。
 * @param {Blob} photoBlob 撮影画像
 * @returns {Promise<{name?: string, category?: string} | null>}
 */
export async function suggestItemInfo(photoBlob) {
  if (proxyUrl()) {
    try {
      const res = await classifyViaProxy(photoBlob);
      if (!res.error) {
        if (!res.result) return null;
        return { name: res.result.name || undefined, category: res.result.category || undefined };
      }
      // res.error === 'proxy-config' | 'quota': 従来のMobileNet経路へフォールバック
    } catch {
      // 通信失敗・タイムアウト等: 従来のMobileNet経路へフォールバック
    }
  } else if (geminiKey()) {
    try {
      const res = await classifyWithGemini(photoBlob);
      if (!res.error) {
        if (!res.result) return null;
        return { name: res.result.name || undefined, category: res.result.category || undefined };
      }
      // res.error === 'auth': 従来のMobileNet経路へフォールバック
    } catch {
      // 通信失敗・タイムアウト等: 従来のMobileNet経路へフォールバック
    }
  }

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
 * 中継サーバURLが設定されていればそちらを最優先で試す。設定不備(URL/Workerの設定に問題がある
 * 場合)は status: 'proxy-error'、利用上限超過は status: 'quota-error' として区別し、それ以外の
 * 失敗(通信・タイムアウト等)は従来のブラウザ内AI(MobileNet)経路にフォールバックする。
 * 中継サーバが未設定で Gemini APIキーが設定されている場合は Gemini を試す。認証エラー
 * (無効なキー)は status: 'auth-error' として区別し、それ以外の失敗は同様に MobileNet
 * 経路にフォールバックする。
 * MobileNet経路では suggestItemInfo() と異なり、失敗理由(モデルのロード/推論失敗 か、
 * 判別はできたがルール表に該当が無いか)を区別して返す。ユーザーが明示的に操作しているため
 * しきい値も MIN_PROBABILITY_MANUAL(0.15)と緩めにしている。
 * この関数自体は例外を投げない。
 * @param {Blob} photoBlob 撮影画像
 * @returns {Promise<
 *   | { status: 'ok', name?: string, category?: string, top: { className: string, probability: number } | null, source?: string }
 *   | { status: 'no-match', top: { className: string, probability: number } | null, source?: string }
 *   | { status: 'model-error' }
 *   | { status: 'auth-error' }
 *   | { status: 'proxy-error' }
 *   | { status: 'quota-error' }
 * >}
 */
export async function analyzePhoto(photoBlob) {
  if (proxyUrl()) {
    try {
      const res = await classifyViaProxy(photoBlob);
      if (res.error === 'proxy-config') return { status: 'proxy-error' };
      if (res.error === 'quota') return { status: 'quota-error' };
      if (res.result) {
        return {
          status: 'ok',
          name: res.result.name || undefined,
          category: res.result.category || undefined,
          top: null,
          source: 'proxy',
        };
      }
      return { status: 'no-match', top: null, source: 'proxy' };
    } catch {
      // 通信失敗・タイムアウト等: 従来のMobileNet経路へフォールバック
    }
  } else if (geminiKey()) {
    try {
      const res = await classifyWithGemini(photoBlob);
      if (res.error === 'auth') return { status: 'auth-error' };
      if (res.result) {
        return {
          status: 'ok',
          name: res.result.name || undefined,
          category: res.result.category || undefined,
          top: null,
          source: 'gemini',
        };
      }
      return { status: 'no-match', top: null, source: 'gemini' };
    } catch {
      // 通信失敗・タイムアウト等: 従来のMobileNet経路へフォールバック
    }
  }

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
        source: 'local',
      };
    }
  }

  const top = predictions && predictions.length
    ? { className: predictions[0].className, probability: predictions[0].probability }
    : null;
  return { status: 'no-match', top, source: 'local' };
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

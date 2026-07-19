// MONO 中継サーバ(Cloudflare Worker) — 持ち物判別専用の窓口。
//
// 目的: Gemini APIキーをブラウザ(localStorage)から排除し、ユーザー自身がデプロイする
// この Worker にだけ持たせる。汎用的な Gemini 中継にはしない — 受け取るのは写真+カテゴリ一覧
// のみで、プロンプトは常にこの Worker 側で固定生成する(呼び出し側が任意の文章を注入すること
// はできない)。
//
// 設置手順は README.md を参照。ALLOWED_ORIGINS は自分の公開先に合わせて編集してください。

const ALLOWED_ORIGINS = ['https://tadao-eng.github.io', 'http://localhost:8000'];
const GEMINI_MODEL = 'gemini-2.5-flash';
const GEMINI_TIMEOUT_MS = 20000;
const MAX_IMAGE_LEN = 8_000_000;
const MAX_CATEGORIES = 40;
const MAX_CATEGORY_LEN = 40;

// app.js の categories.js の DEFAULT_CATEGORIES と同一(Worker はアプリの localStorage を
// 参照できないため、リクエストで渡されたカテゴリ一覧が不正な場合のフォールバックとして持つ)。
const DEFAULT_CATEGORIES = [
  '衣類', '靴', 'バッグ', '本', 'ガジェット', 'キッチン', '日用品', '家具', '趣味', '美容', '書類', 'その他',
];

// ---------- 純関数(ロジック本体。node からも import して単体検証できるよう export する) ----------

/**
 * ai.js の geminiPrompt() と同一文面のプロンプトを組み立てる。
 * @param {string[]} categories
 * @returns {string}
 */
export function buildPrompt(categories) {
  return 'この写真に写っている主要な持ち物1点を判定してください。JSONのみで回答: ' +
    `{"name": 日本語の簡潔な品名(最大20文字), "category": 次のリストから最も近い1つ ${JSON.stringify(categories)}}。` +
    '何が写っているか判定できない場合は {"name": null, "category": null}';
}

/**
 * mime が 'image/' で始まる文字列でなければ既定値に置き換える。
 * @param {*} mime
 * @returns {string}
 */
export function sanitizeMime(mime) {
  if (typeof mime === 'string' && mime.startsWith('image/')) return mime;
  return 'image/jpeg';
}

/**
 * categories を string配列・最大40個・各要素40文字以下にサニタイズする。
 * 配列でない/要素数超過/文字列でない要素/長すぎる要素のいずれかがあれば、
 * 全体を既定カテゴリ配列にフォールバックする(部分的な切り詰めは行わない)。
 * @param {*} categories
 * @returns {string[]}
 */
export function sanitizeCategories(categories) {
  if (!Array.isArray(categories) || categories.length === 0) return DEFAULT_CATEGORIES.slice();
  if (categories.length > MAX_CATEGORIES) return DEFAULT_CATEGORIES.slice();
  const allValid = categories.every(
    (c) => typeof c === 'string' && c.trim().length > 0 && c.trim().length <= MAX_CATEGORY_LEN
  );
  if (!allValid) return DEFAULT_CATEGORIES.slice();
  return categories.map((c) => c.trim());
}

/**
 * リクエストボディを検証・サニタイズする。
 * image が string でない/空/長すぎる場合のみ不正ボディ(null)として扱う。
 * mime / categories は不正でも既定値へのフォールバックで吸収し、null を返さない。
 * @param {*} body
 * @returns {{ image: string, mime: string, categories: string[] } | null}
 */
export function parseRequestBody(body) {
  if (!body || typeof body !== 'object') return null;
  if (typeof body.image !== 'string' || body.image.length === 0 || body.image.length > MAX_IMAGE_LEN) {
    return null;
  }
  return {
    image: body.image,
    mime: sanitizeMime(body.mime),
    categories: sanitizeCategories(body.categories),
  };
}

/**
 * Gemini の応答テキスト(```json フェンス付きのことがある)をパースし、
 * アプリに返す形 { result: {name, category} | null } に変換する。
 * JSON として解釈できない場合は例外を投げる(呼び出し側で upstream エラー扱いにする)。
 * @param {string} text
 * @returns {{ result: { name: string|null, category: string|null } | null }}
 */
export function parseGeminiText(text) {
  const cleaned = (text || '').trim()
    .replace(/^```json\s*/i, '')
    .replace(/^```\s*/, '')
    .replace(/```\s*$/, '')
    .trim();
  const parsed = JSON.parse(cleaned);
  if (!parsed.name && !parsed.category) return { result: null };
  return { result: { name: parsed.name || null, category: parsed.category || null } };
}

/**
 * CORS ヘッダを組み立てる。Origin が許可リストにある場合のみ Allow-Origin 等を付与する。
 * @param {string|null} origin
 * @returns {Record<string,string>}
 */
export function corsHeaders(origin) {
  const headers = { 'Content-Type': 'application/json' };
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Access-Control-Allow-Methods'] = 'POST';
    headers['Access-Control-Allow-Headers'] = 'Content-Type';
  }
  return headers;
}

function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), { status, headers });
}

// ---------- Worker本体 ----------

export default {
  /**
   * @param {Request} request
   * @param {{ GEMINI_API_KEY?: string }} env
   */
  async fetch(request, env) {
    const origin = request.headers.get('Origin');
    const headers = corsHeaders(origin);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers });
    }
    if (request.method !== 'POST') {
      return json({ error: 'method-not-allowed' }, 405, headers);
    }
    if (!origin || !ALLOWED_ORIGINS.includes(origin)) {
      return json({ error: 'forbidden' }, 403, headers);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: 'bad-request' }, 400, headers);
    }

    const parsed = parseRequestBody(body);
    if (!parsed) {
      return json({ error: 'bad-request' }, 400, headers);
    }

    if (!env.GEMINI_API_KEY) {
      return json({ error: 'no-key' }, 500, headers);
    }

    const prompt = buildPrompt(parsed.categories);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), GEMINI_TIMEOUT_MS);
    let res;
    try {
      res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`,
        {
          method: 'POST',
          headers: { 'x-goog-api-key': env.GEMINI_API_KEY, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contents: [{
              parts: [
                { inline_data: { mime_type: parsed.mime, data: parsed.image } },
                { text: prompt },
              ],
            }],
            generationConfig: { response_mime_type: 'application/json' },
          }),
          signal: ctrl.signal,
        }
      );
    } catch {
      return json({ error: 'upstream' }, 502, headers);
    } finally {
      clearTimeout(timer);
    }

    if (!res.ok) {
      if (res.status === 429) return json({ error: 'quota' }, 429, headers);
      return json({ error: 'upstream' }, 502, headers);
    }

    try {
      const data = await res.json();
      const text = (data?.candidates?.[0]?.content?.parts || []).map((p) => p.text || '').join('');
      const result = parseGeminiText(text);
      return json(result, 200, headers);
    } catch {
      return json({ error: 'upstream' }, 502, headers);
    }
  },
};

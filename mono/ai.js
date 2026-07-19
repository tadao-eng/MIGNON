// 画像・バーコードからの品目情報推定(拡張ポイント)。
//
// 将来カメラ画像からのAI自動推定を追加する場合は suggestItemInfo() の中身を
// 差し替えるだけでよい(app.js は戻り値 {name, category} | null しか見ない)。
// 例: 画像を Vision API / Claude API 等に送り、品目名とカテゴリを受け取る。

/**
 * 写真から品目名・カテゴリを推定する。
 * @param {Blob} _photoBlob 撮影画像
 * @returns {Promise<{name?: string, category?: string} | null>}
 */
export async function suggestItemInfo(_photoBlob) {
  // 現状はオフライン完結のため推定なし(手動入力)。
  return null;
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

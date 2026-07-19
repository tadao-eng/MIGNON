// MONO — 持ち物管理 PWA 本体
import { putItem, getItem, deleteItem, getAllItems, newId } from './db.js';
import { suggestItemInfo, analyzePhoto, lookupBarcode, preloadModel } from './ai.js';
import { startScan } from './scanner.js';
import { getCategories, setCategories } from './categories.js';

const UNCATEGORIZED = '未分類';
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

const $ = (sel) => document.querySelector(sel);

const state = {
  items: [],
  filter: 'all',
  sort: localStorage.getItem('mono.sort') || 'new',
  listMode: localStorage.getItem('mono.layout') === 'list',
  editingId: null,
  detailId: null,
  draftPhoto: null,
};

let objectURLs = [];
function photoURL(blob) {
  const url = URL.createObjectURL(blob);
  objectURLs.push(url);
  return url;
}
function revokeURLs() {
  objectURLs.forEach((u) => URL.revokeObjectURL(u));
  objectURLs = [];
}

// ---------- 汎用 ----------

let toastTimer = null;
function toast(msg, durationMs = 2200) {
  const el = $('#toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, durationMs);
}

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fmtDate(v) {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`;
}

function acquiredTime(item) {
  const t = new Date(item.acquiredAt || item.createdAt).getTime();
  return Number.isNaN(t) ? new Date(item.createdAt).getTime() : t;
}

const owned = () => state.items.filter((i) => i.status === 'owned');
const released = () => state.items.filter((i) => i.status === 'released');

// ---------- ビュー切替 ----------

function switchView(name) {
  ['list', 'add', 'history', 'stats'].forEach((v) => {
    $(`#view-${v}`).hidden = v !== name;
  });
  document.querySelectorAll('.tab').forEach((b) => {
    b.classList.toggle('active', b.dataset.view === name);
  });
  window.scrollTo(0, 0);
}

document.querySelectorAll('.tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    switchView(btn.dataset.view);
  });
});

// ---------- 描画 ----------

function renderAll() {
  revokeURLs();
  renderWeeklyDelta();
  renderChips();
  renderList();
  renderHistory();
  renderStats();
}

function renderWeeklyDelta() {
  const since = Date.now() - WEEK_MS;
  const added = state.items.filter((i) => acquiredTime(i) >= since).length;
  const removed = released().filter((i) => new Date(i.releasedAt).getTime() >= since).length;
  $('#weekly-delta').innerHTML =
    `今週 <span class="plus">+${added}</span> / <span class="minus">−${removed}</span>`;
}

function renderChips() {
  const counts = new Map();
  owned().forEach((i) => {
    const c = i.category || UNCATEGORIZED;
    counts.set(c, (counts.get(c) || 0) + 1);
  });
  const cats = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
  if (state.filter !== 'all' && !counts.has(state.filter)) state.filter = 'all';

  const wrap = $('#category-chips');
  wrap.innerHTML = '';
  const mk = (label, value) => {
    const b = document.createElement('button');
    b.className = 'chip' + (state.filter === value ? ' active' : '');
    b.textContent = label;
    b.addEventListener('click', () => {
      state.filter = value;
      renderChips();
      renderList();
    });
    wrap.appendChild(b);
  };
  mk('すべて', 'all');
  cats.forEach((c) => mk(`${c} ${counts.get(c)}`, c));

  const manage = document.createElement('button');
  manage.id = 'manage-categories-chip';
  manage.className = 'chip';
  manage.textContent = 'カテゴリ編集';
  manage.addEventListener('click', () => openCategoryDialog());
  wrap.appendChild(manage);
}

function sortItems(list) {
  const s = [...list];
  switch (state.sort) {
    case 'old':
      return s.sort((a, b) => acquiredTime(a) - acquiredTime(b));
    case 'name':
      return s.sort((a, b) => a.name.localeCompare(b.name, 'ja'));
    case 'category':
      return s.sort((a, b) =>
        (a.category || UNCATEGORIZED).localeCompare(b.category || UNCATEGORIZED, 'ja') ||
        a.name.localeCompare(b.name, 'ja'));
    default: // new
      return s.sort((a, b) => acquiredTime(b) - acquiredTime(a));
  }
}

function renderList() {
  const grid = $('#item-grid');
  grid.classList.toggle('list-mode', state.listMode);
  $('#layout-toggle').textContent = state.listMode ? '⊞' : '≡';
  grid.innerHTML = '';

  let list = owned();
  if (state.filter !== 'all') {
    list = list.filter((i) => (i.category || UNCATEGORIZED) === state.filter);
  }
  list = sortItems(list);

  $('#item-count').textContent = `全 ${list.length} 点`;
  $('#empty-list').hidden = owned().length > 0;

  list.forEach((item) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.addEventListener('click', () => openDetail(item.id));

    if (item.photo) {
      const img = document.createElement('img');
      img.className = 'card-photo';
      img.loading = 'lazy';
      img.alt = item.name;
      img.src = photoURL(item.photo);
      card.appendChild(img);
    } else {
      const ph = document.createElement('div');
      ph.className = 'card-photo placeholder';
      ph.textContent = '·';
      card.appendChild(ph);
    }

    const body = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'card-name';
    name.textContent = item.name;
    body.appendChild(name);
    const sub = document.createElement('div');
    sub.className = 'card-sub';
    sub.textContent = `${item.category || UNCATEGORIZED} · ${fmtDate(item.acquiredAt)}`;
    body.appendChild(sub);
    card.appendChild(body);

    grid.appendChild(card);
  });
}

// ---------- 履歴 ----------

function renderHistory() {
  const wrap = $('#history-list');
  wrap.innerHTML = '';
  const list = released().sort(
    (a, b) => new Date(b.releasedAt).getTime() - new Date(a.releasedAt).getTime());
  $('#empty-history').hidden = list.length > 0;

  list.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'history-item';

    if (item.photo) {
      const img = document.createElement('img');
      img.alt = item.name;
      img.src = photoURL(item.photo);
      row.appendChild(img);
    } else {
      const ph = document.createElement('div');
      ph.className = 'no-photo';
      ph.textContent = '·';
      row.appendChild(ph);
    }

    const body = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'history-name';
    name.textContent = item.name;
    const sub = document.createElement('div');
    sub.className = 'history-sub';
    sub.innerHTML = `${fmtDate(item.releasedAt)} <span class="method">${item.releaseMethod || ''}</span>` +
      (item.releaseReason ? ` — ${escapeHTML(item.releaseReason)}` : '');
    body.appendChild(name);
    body.appendChild(sub);
    row.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'history-actions';
    const back = document.createElement('button');
    back.textContent = '戻す';
    back.addEventListener('click', async () => {
      item.status = 'owned';
      delete item.releasedAt;
      delete item.releaseMethod;
      delete item.releaseReason;
      await putItem(item);
      await reload();
      toast('持ち物に戻しました');
    });
    const del = document.createElement('button');
    del.textContent = '削除';
    del.addEventListener('click', async () => {
      if (!confirm(`「${item.name}」の記録を完全に削除しますか?`)) return;
      await deleteItem(item.id);
      await reload();
      toast('削除しました');
    });
    actions.appendChild(back);
    actions.appendChild(del);
    row.appendChild(actions);

    wrap.appendChild(row);
  });
}

function escapeHTML(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------- 分析 ----------

function renderStats() {
  const cur = owned().length;
  const since = Date.now() - WEEK_MS;
  const added = state.items.filter((i) => acquiredTime(i) >= since).length;
  const removed = released().filter((i) => new Date(i.releasedAt).getTime() >= since).length;
  const net = added - removed;

  $('#stat-total').textContent = cur;
  const weekEl = $('#stat-week');
  weekEl.textContent = net > 0 ? `+${net}` : net < 0 ? `−${Math.abs(net)}` : '±0';
  weekEl.classList.toggle('up', net > 0);
  $('#stat-released').textContent = released().length;

  renderTrendChart();
  renderCategoryBars();
}

// 過去12週の各週末時点での所持数を数える
function renderTrendChart() {
  const WEEKS = 12;
  const now = Date.now();
  const points = [];
  for (let w = WEEKS - 1; w >= 0; w--) {
    const t = now - w * WEEK_MS;
    const count = state.items.filter((i) => {
      if (acquiredTime(i) > t) return false;
      if (i.status === 'released' && new Date(i.releasedAt).getTime() <= t) return false;
      return true;
    }).length;
    points.push(count);
  }

  const W = 320, H = 96, PAD = 8;
  const max = Math.max(...points, 1);
  const min = Math.min(...points);
  const range = Math.max(max - min, 1);
  const x = (i) => PAD + (i * (W - PAD * 2)) / (WEEKS - 1);
  const y = (v) => H - PAD - ((v - min) * (H - PAD * 2)) / range;
  const poly = points.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const last = points[points.length - 1];

  $('#trend-chart').innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="総アイテム数の推移">
      <polyline points="${poly}" fill="none" stroke="#1A1A1A" stroke-width="1.5"
        stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${x(WEEKS - 1)}" cy="${y(last)}" r="3" fill="#C0563F"/>
      <text x="${W - PAD}" y="${Math.max(y(last) - 8, 10)}" text-anchor="end"
        font-size="11" fill="#9A9A9A">${last}</text>
    </svg>
    <div class="muted" style="display:flex;justify-content:space-between;margin-top:6px">
      <span>12週前</span><span>現在</span>
    </div>`;
}

function renderCategoryBars() {
  const counts = new Map();
  owned().forEach((i) => {
    const c = i.category || UNCATEGORIZED;
    counts.set(c, (counts.get(c) || 0) + 1);
  });
  const total = owned().length;
  const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const max = rows.length ? rows[0][1] : 0;

  const wrap = $('#category-bars');
  wrap.innerHTML = '';
  rows.forEach(([cat, n], idx) => {
    const row = document.createElement('div');
    row.className = 'cat-bar-row' + (idx === 0 && rows.length > 1 ? ' top' : '');
    row.innerHTML = `
      <span class="cat-bar-label">${escapeHTML(cat)}</span>
      <span class="cat-bar-track"><span class="cat-bar-fill" style="width:${(n / max) * 100}%"></span></span>
      <span class="cat-bar-count">${n}</span>`;
    wrap.appendChild(row);
  });

  const hint = $('#stats-hint');
  if (rows.length > 1 && rows[0][1] / total >= 0.3) {
    hint.textContent = `「${rows[0][0]}」が全体の ${Math.round((rows[0][1] / total) * 100)}% を占めています。`;
  } else if (total === 0) {
    hint.textContent = '持ち物を登録すると内訳が表示されます。';
  } else {
    hint.textContent = '';
  }
}

// ---------- AI設定(中継サーバURL / Gemini APIキー) ----------

const GEMINI_KEY_STORAGE = 'mono.geminiKey';
const PROXY_URL_STORAGE = 'mono.proxyUrl';

function renderGeminiStatus() {
  const hasProxy = !!(localStorage.getItem(PROXY_URL_STORAGE) || '').trim();
  const hasKey = !!(localStorage.getItem(GEMINI_KEY_STORAGE) || '').trim();
  $('#gemini-status').textContent = hasProxy
    ? '中継サーバ使用中(APIキーはサーバ側)'
    : hasKey
      ? 'Gemini 使用中(高精度判別が有効)'
      : '未設定(端末内AIで判別します)';
  $('#gemini-clear').hidden = !hasKey;
  $('#proxy-clear').hidden = !hasProxy;
}

$('#proxy-save').addEventListener('click', () => {
  const value = $('#proxy-url').value.trim();
  if (!value) return;
  if (!value.startsWith('https://')) {
    toast('中継サーバURLは https:// で始まる必要があります', 4000);
    return;
  }
  localStorage.setItem(PROXY_URL_STORAGE, value);
  $('#proxy-url').value = '';
  renderGeminiStatus();
  toast('中継サーバを使用します(キーは端末に不要)');
});

$('#proxy-clear').addEventListener('click', () => {
  localStorage.removeItem(PROXY_URL_STORAGE);
  renderGeminiStatus();
  toast('中継サーバの設定を解除しました');
});

$('#gemini-save').addEventListener('click', () => {
  const value = $('#gemini-key').value.trim();
  if (!value) return;
  localStorage.setItem(GEMINI_KEY_STORAGE, value);
  $('#gemini-key').value = '';
  renderGeminiStatus();
  toast('Gemini を有効にしました');
});

$('#gemini-clear').addEventListener('click', () => {
  localStorage.removeItem(GEMINI_KEY_STORAGE);
  renderGeminiStatus();
  toast('端末内AIに戻しました');
});

// ---------- 追加 / 編集フォーム ----------

function initCategoryDatalist() {
  const existing = new Set(state.items.map((i) => i.category).filter(Boolean));
  const all = [...new Set([...getCategories(), ...existing])];
  $('#category-list').innerHTML = all.map((c) => `<option value="${escapeHTML(c)}">`).join('');
}

// 追加/編集フォームのカテゴリ入力欄直下に、マスタ全カテゴリのチップ列を表示する。
// タップで #f-category に値を設定し、入力欄の値と一致するチップに .active を付ける。
function renderCategoryPicker() {
  const wrap = $('#category-picker');
  const current = $('#f-category').value.trim();
  wrap.innerHTML = '';
  getCategories().forEach((c) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip' + (c === current ? ' active' : '');
    b.textContent = c;
    b.addEventListener('click', () => {
      $('#f-category').value = c;
      renderCategoryPicker();
    });
    wrap.appendChild(b);
  });
}

$('#f-category').addEventListener('input', () => {
  const current = $('#f-category').value.trim();
  $('#category-picker').querySelectorAll('.chip').forEach((b) => {
    b.classList.toggle('active', b.textContent === current);
  });
});

function resetForm() {
  state.editingId = null;
  state.draftPhoto = null;
  $('#add-form').reset();
  $('#f-acquired').value = todayStr();
  $('#add-title').textContent = '追加';
  $('#save-btn').textContent = '登録する';
  $('#cancel-edit').hidden = true;
  updatePhotoPreview();
  initCategoryDatalist();
  renderCategoryPicker();
}

let previewURL = null; // 一覧の再描画と独立して管理する(誤って失効させない)
function updatePhotoPreview() {
  const img = $('#photo-img');
  const ph = $('#photo-placeholder');
  if (previewURL) {
    URL.revokeObjectURL(previewURL);
    previewURL = null;
  }
  if (state.draftPhoto) {
    previewURL = URL.createObjectURL(state.draftPhoto);
    img.src = previewURL;
    img.hidden = false;
    ph.hidden = true;
    $('#photo-clear').hidden = false;
    $('#analyze-btn').hidden = false;
  } else {
    img.hidden = true;
    img.removeAttribute('src');
    ph.hidden = false;
    $('#photo-clear').hidden = true;
    $('#analyze-btn').hidden = true;
  }
}

// 撮影画像を長辺1024pxのJPEGに縮小して保存容量を抑える
async function processPhoto(file) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
      .catch(() => createImageBitmap(file));
    const MAX = 1024;
    const scale = Math.min(1, MAX / Math.max(bmp.width, bmp.height));
    const w = Math.max(1, Math.round(bmp.width * scale));
    const h = Math.max(1, Math.round(bmp.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(bmp, 0, 0, w, h);
    bmp.close();
    const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.82));
    return blob || file;
  } catch {
    return file; // 縮小に失敗したら原本をそのまま使う
  }
}

$('#photo-preview').addEventListener('click', () => $('#photo-input').click());
$('#photo-preview').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    $('#photo-input').click();
  }
});

// 写真ファイル選択後の共通処理(カメラ撮影 / アルバム選択のどちらからでも呼ばれる)
async function handlePhotoFile(file) {
  if (!file) return;
  state.draftPhoto = await processPhoto(file);
  updatePhotoPreview();

  // ブラウザ内AI(TensorFlow.js MobileNet)で品目名・カテゴリを推定し、空欄のみ自動入力する
  const suggestion = await suggestItemInfo(state.draftPhoto);
  if (suggestion) {
    let filled = false;
    if (suggestion.name && !$('#f-name').value) { $('#f-name').value = suggestion.name; filled = true; }
    if (suggestion.category && !$('#f-category').value) { $('#f-category').value = suggestion.category; filled = true; }
    if (filled) toast('AIが品目を推定しました(修正できます)');
  }
}

$('#photo-input').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  await handlePhotoFile(file);
});

$('#gallery-btn').addEventListener('click', () => $('#photo-input-gallery').click());

$('#photo-input-gallery').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  await handlePhotoFile(file);
});

$('#photo-clear').addEventListener('click', () => {
  state.draftPhoto = null;
  updatePhotoPreview();
});

$('#analyze-btn').addEventListener('click', async () => {
  const btn = $('#analyze-btn');
  if (!state.draftPhoto || btn.disabled) return;
  btn.disabled = true;
  btn.textContent = '分析中…';
  try {
    const result = await analyzePhoto(state.draftPhoto);
    if (result.status === 'ok') {
      if (result.name) $('#f-name').value = result.name;
      if (result.category) $('#f-category').value = result.category;
      const label = [result.name, result.category].filter(Boolean).join(' / ');
      toast(`「${label}」と推定しました`);
    } else if (result.status === 'no-match') {
      if (result.top) {
        const pct = Math.round(result.top.probability * 100);
        toast(`判別できませんでした(近い候補: ${result.top.className} ${pct}%)`, 4000);
      } else {
        toast('判別できませんでした。角度や明るさを変えて撮り直してみてください', 4000);
      }
    } else if (result.status === 'auth-error') {
      toast('Gemini APIキーが無効のようです。「分析」タブのAI設定を確認してください', 4000);
    } else if (result.status === 'proxy-error') {
      toast('中継サーバの設定に問題があるようです。URLとWorkerの設定を確認してください', 4000);
    } else if (result.status === 'quota-error') {
      toast('AIの利用上限に達しています。しばらくしてから試してください', 4000);
    } else {
      toast('AIモデルを読み込めませんでした。通信環境を確認してもう一度試してください', 4000);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'AI分析';
  }
});

$('#cancel-edit').addEventListener('click', () => {
  resetForm();
  switchView('list');
});

$('#add-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = $('#f-name').value.trim();
  if (!name) return;

  const base = state.editingId
    ? await getItem(state.editingId)
    : { id: newId(), createdAt: new Date().toISOString(), status: 'owned' };
  if (!base) return;

  base.name = name;
  base.category = $('#f-category').value.trim();
  base.acquiredAt = $('#f-acquired').value || todayStr();
  base.barcode = $('#f-barcode').value.trim();
  base.note = $('#f-note').value.trim();
  base.photo = state.draftPhoto;

  await putItem(base);
  const wasEditing = !!state.editingId;
  resetForm();
  await reload();
  switchView('list');
  toast(wasEditing ? '更新しました' : '登録しました');
});

// ---------- バーコード読取 ----------

let scanner = null;

async function openScanner() {
  const dialog = $('#scan-dialog');
  const status = $('#scan-status');
  status.textContent = 'カメラを起動しています…';
  dialog.showModal();
  try {
    scanner = await startScan(
      $('#scan-video'),
      async (code) => {
        closeScanner();
        $('#f-barcode').value = code;
        toast(`読み取りました: ${code}`);
        // 商品名の自動補完(ヒットしなければ何もしない)
        if (!$('#f-name').value) {
          const info = await lookupBarcode(code);
          if (info?.name && !$('#f-name').value) {
            $('#f-name').value = info.name;
            toast('商品名を自動入力しました');
          }
        }
      },
      (msg) => { status.textContent = msg; }
    );
  } catch (err) {
    status.textContent = err.message || 'カメラを起動できませんでした';
  }
}

function closeScanner() {
  scanner?.stop();
  scanner = null;
  const dialog = $('#scan-dialog');
  if (dialog.open) dialog.close();
}

$('#scan-btn').addEventListener('click', openScanner);
$('#scan-close').addEventListener('click', closeScanner);
$('#scan-dialog').addEventListener('close', () => { scanner?.stop(); scanner = null; });

// ---------- 詳細 / 手放す ----------

function openDetail(id) {
  const item = state.items.find((i) => i.id === id);
  if (!item) return;
  state.detailId = id;

  const photo = $('#d-photo');
  if (item.photo) {
    photo.src = photoURL(item.photo);
    photo.hidden = false;
  } else {
    photo.hidden = true;
    photo.removeAttribute('src');
  }
  $('#d-name').textContent = item.name;

  const meta = [
    ['カテゴリ', item.category || UNCATEGORIZED],
    ['取得日', fmtDate(item.acquiredAt)],
  ];
  if (item.barcode) meta.push(['バーコード', item.barcode]);
  if (item.note) meta.push(['メモ', item.note]);
  $('#d-meta').innerHTML = meta
    .map(([k, v]) => `<dt>${k}</dt><dd>${escapeHTML(String(v))}</dd>`)
    .join('');

  $('#detail-dialog').showModal();
}

$('#d-close').addEventListener('click', () => $('#detail-dialog').close());

$('#d-edit').addEventListener('click', () => {
  const item = state.items.find((i) => i.id === state.detailId);
  if (!item) return;
  $('#detail-dialog').close();

  state.editingId = item.id;
  state.draftPhoto = item.photo || null;
  initCategoryDatalist();
  $('#f-name').value = item.name;
  $('#f-category').value = item.category || '';
  $('#f-acquired').value = item.acquiredAt || todayStr();
  $('#f-barcode').value = item.barcode || '';
  $('#f-note').value = item.note || '';
  $('#add-title').textContent = '編集';
  $('#save-btn').textContent = '更新する';
  $('#cancel-edit').hidden = false;
  updatePhotoPreview();
  renderCategoryPicker();
  switchView('add');
});

$('#d-release').addEventListener('click', () => {
  const item = state.items.find((i) => i.id === state.detailId);
  if (!item) return;
  $('#detail-dialog').close();
  $('#r-item-name').textContent = item.name;
  $('#r-reason').value = '';
  $('#release-dialog').showModal();
});

$('#r-cancel').addEventListener('click', () => $('#release-dialog').close());

$('#r-confirm').addEventListener('click', async () => {
  const item = await getItem(state.detailId);
  if (!item) return;
  item.status = 'released';
  item.releasedAt = new Date().toISOString();
  item.releaseMethod = document.querySelector('input[name="r-method"]:checked').value;
  item.releaseReason = $('#r-reason').value.trim();
  await putItem(item);
  $('#release-dialog').close();
  await reload();
  toast('手放しました');
});

// ---------- 一覧の操作 ----------

$('#sort-select').addEventListener('change', (e) => {
  state.sort = e.target.value;
  localStorage.setItem('mono.sort', state.sort);
  renderList();
});

$('#layout-toggle').addEventListener('click', () => {
  state.listMode = !state.listMode;
  localStorage.setItem('mono.layout', state.listMode ? 'list' : 'grid');
  renderList();
});

// ---------- カテゴリ管理 ----------

function renderCategoryDialogList() {
  const wrap = $('#cat-list');
  wrap.innerHTML = '';
  getCategories().forEach((cat) => {
    const row = document.createElement('div');
    row.className = 'cat-row';

    const label = document.createElement('span');
    label.textContent = cat;
    row.appendChild(label);

    const actions = document.createElement('div');
    actions.className = 'history-actions';
    const renameBtn = document.createElement('button');
    renameBtn.type = 'button';
    renameBtn.textContent = '変更';
    renameBtn.addEventListener('click', () => renameCategory(cat));
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.textContent = '削除';
    delBtn.addEventListener('click', () => deleteCategory(cat));
    actions.appendChild(renameBtn);
    actions.appendChild(delBtn);
    row.appendChild(actions);

    wrap.appendChild(row);
  });
}

// カテゴリマスタ/アイテムの変更後、追加画面のdatalist・チップピッカーを最新化する
// (renderChips 等は reload() 経由の renderAll() で更新される)
function refreshCategoryUI() {
  initCategoryDatalist();
  renderCategoryPicker();
}

function openCategoryDialog() {
  $('#cat-new-input').value = '';
  renderCategoryDialogList();
  $('#category-dialog').showModal();
}

$('#cat-close').addEventListener('click', () => $('#category-dialog').close());

$('#cat-add-btn').addEventListener('click', () => {
  const name = $('#cat-new-input').value.trim();
  if (!name) { toast('カテゴリ名を入力してください'); return; }
  const cats = getCategories();
  if (cats.includes(name)) { toast('すでに存在するカテゴリです'); return; }
  setCategories([...cats, name]);
  $('#cat-new-input').value = '';
  renderCategoryDialogList();
  refreshCategoryUI();
  toast(`「${name}」を追加しました`);
});

async function renameCategory(oldName) {
  const input = prompt('新しいカテゴリ名', oldName);
  if (input === null) return;
  const newName = input.trim();
  if (!newName) { toast('カテゴリ名を入力してください'); return; }
  if (newName === oldName) return;
  const cats = getCategories();
  if (cats.includes(newName)) { toast('すでに存在するカテゴリです'); return; }

  setCategories(cats.map((c) => (c === oldName ? newName : c)));
  const targets = state.items.filter((i) => i.category === oldName);
  for (const item of targets) {
    item.category = newName;
    await putItem(item);
  }
  await reload();
  renderCategoryDialogList();
  refreshCategoryUI();
  toast(`「${oldName}」を「${newName}」に変更しました`);
}

async function deleteCategory(name) {
  const n = state.items.filter((i) => i.category === name).length;
  const msg = n > 0
    ? `「${name}」を削除しますか?${n}点の持ち物は「未分類」になります`
    : `「${name}」を削除しますか?`;
  if (!confirm(msg)) return;

  setCategories(getCategories().filter((c) => c !== name));
  const targets = state.items.filter((i) => i.category === name);
  for (const item of targets) {
    item.category = '';
    await putItem(item);
  }
  await reload();
  renderCategoryDialogList();
  refreshCategoryUI();
  toast(`「${name}」を削除しました`);
}

// ---------- インストール導線 ----------
// Android/Chrome 系: beforeinstallprompt を捕まえてワンタップでインストール。
// iOS Safari: 同イベントが無いため「共有 → ホーム画面に追加」の手順を案内する。

const INSTALL_DISMISS_KEY = 'mono.installDismissed';
let installPrompt = null;

function isStandalone() {
  return matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
}

function showInstallBanner(text, withButton) {
  if (isStandalone() || localStorage.getItem(INSTALL_DISMISS_KEY)) return;
  $('#install-text').textContent = text;
  $('#install-btn').hidden = !withButton;
  $('#install-banner').hidden = false;
}

function hideInstallBanner() {
  $('#install-banner').hidden = true;
}

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  installPrompt = e;
  showInstallBanner('ホーム画面に追加すると、アプリとして使えます。', true);
});

window.addEventListener('appinstalled', () => {
  installPrompt = null;
  hideInstallBanner();
  toast('インストールしました');
});

$('#install-btn').addEventListener('click', async () => {
  if (!installPrompt) return;
  hideInstallBanner();
  installPrompt.prompt();
  await installPrompt.userChoice.catch(() => {});
  installPrompt = null;
});

$('#install-close').addEventListener('click', () => {
  localStorage.setItem(INSTALL_DISMISS_KEY, '1');
  hideInstallBanner();
});

function maybeShowIOSInstallHint() {
  const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1); // iPadOS対策
  if (isIOS && !isStandalone()) {
    showInstallBanner('Safariの共有ボタンから「ホーム画面に追加」でアプリとして使えます。', false);
  }
}

// ---------- 起動 ----------

async function reload() {
  state.items = await getAllItems();
  renderAll();
}

async function init() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
  $('#sort-select').value = state.sort;
  maybeShowIOSInstallHint();
  resetForm();
  renderGeminiStatus();
  await reload();

  // 起動直後の描画が落ち着いてからAIモデルを裏で先読みする(初回判別の待ちをなくす)
  if ('requestIdleCallback' in window) {
    requestIdleCallback(() => preloadModel(), { timeout: 5000 });
  } else {
    setTimeout(() => preloadModel(), 2500);
  }
}

init();

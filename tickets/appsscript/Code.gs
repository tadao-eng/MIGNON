/**
 * ヨーロッパ企画 チケット受け渡し表 — サーバー側
 *
 * 状態はこのスクリプトのプロパティに入る(別途スプレッドシートを作る必要はない)。
 * ウェブアプリは「実行するユーザー: 自分」「アクセスできるユーザー: 全員」で
 * デプロイすること。全員の書き込みが同じ 1 か所に集まる。
 */

var DATES = [
  { id: 'd1017', month: 10, day: 17, dow: '土' },
  { id: 'd1018', month: 10, day: 18, dow: '日' },
  { id: 'd1024', month: 10, day: 24, dow: '土' },
  { id: 'd1025', month: 10, day: 25, dow: '日' }
];
var PER_DATE = 4;
var STORE_KEY = 'slots.v1';
var LOCK_WAIT_MS = 10000;

/** ウェブアプリの入口。 */
function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('ヨーロッパ企画 チケット受け渡し表')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/** 受け付けてよい枠 ID の一覧。リンクを知る誰もが呼べるので、必ず照合する。 */
function validIds_() {
  var ids = [];
  for (var i = 0; i < DATES.length; i++) {
    for (var n = 1; n <= PER_DATE; n++) {
      ids.push(DATES[i].id + '-' + n);
    }
  }
  return ids;
}

function readState_() {
  var raw = PropertiesService.getScriptProperties().getProperty(STORE_KEY);
  if (!raw) return {};
  try {
    var parsed = JSON.parse(raw);
    return (parsed && typeof parsed === 'object') ? parsed : {};
  } catch (e) {
    return {};
  }
}

/** 画面から呼ぶ: 現在の全枠の状態。 */
function getState() {
  return readState_();
}

/** 画面から呼ぶ: 1 枠を付ける / 外す。戻り値は更新後の全体。 */
function setSlot(id, held) {
  if (validIds_().indexOf(id) === -1) {
    throw new Error('その枠は存在しません。ページを開き直してください。');
  }

  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(LOCK_WAIT_MS);
  } catch (e) {
    throw new Error('ほかの人が操作中です。少し待ってもう一度どうぞ。');
  }

  try {
    var state = readState_();
    if (held) {
      state[id] = { held: true, at: new Date().toISOString() };
    } else {
      delete state[id];
    }
    PropertiesService.getScriptProperties().setProperty(STORE_KEY, JSON.stringify(state));
    return state;
  } finally {
    lock.releaseLock();
  }
}

/**
 * 手動用。エディタでこの関数を実行すると全部のチェックが消える。
 * ウェブアプリの画面からは呼べないので、押し間違いで消えることはない。
 */
function resetAll() {
  PropertiesService.getScriptProperties().deleteProperty(STORE_KEY);
}

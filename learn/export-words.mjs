// index.html 内の教材データを words.json / curriculum.json に書き出すスクリプト。
// 教材データの正本は index.html。単語・文法を追加・変更したら必ず再実行すること:
//   node learn/export-words.mjs
import { readFileSync, writeFileSync } from 'fs';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');

function grabArray(name) {
  const m = html.match(new RegExp('const ' + name + ' = (\\[[\\s\\S]*?\\n\\]);'));
  if (!m) throw new Error(name + ' not found in index.html');
  return eval(m[1]);
}
function grabObject(name) {
  const m = html.match(new RegExp('const ' + name + ' = (\\{[\\s\\S]*?\\n\\});'));
  if (!m) throw new Error(name + ' not found in index.html');
  return eval('(' + m[1] + ')');
}

const EN = grabArray('EN_WORDS');
const ID = grabArray('ID_WORDS');
const ROADMAP = grabArray('ROADMAP');
const GRAMMAR = grabObject('GRAMMAR');

const toObj = w => ({ word: w[0], meaning: w[1], category: w[2], ...(w[3] ? { forms: w[3] } : {}) });

/* ---------- words.json: 全単語 + 週テーマ ---------- */
const words = {
  app: 'MIGNON LINGO',
  updated: new Date().toISOString().slice(0, 10),
  note: '英語×インドネシア語 90日集中プログラムの単語データ。LINEボット等の外部ツールが読む用。',
  roadmap: ROADMAP.map((r, i) => ({ week: i + 1, theme: r[0], goal: r[1] })),
  en: EN.map(toObj),
  id: ID.map(toObj),
};
writeFileSync(new URL('./words.json', import.meta.url), JSON.stringify(words, null, 1), 'utf8');

/* ---------- curriculum.json: 180日分の配信カリキュラム ----------
   毎日: 英語5語 + インドネシア語5語(計10語) + 文法1課(英/イ交互)。
   さらに各日に extra(翌日分の先取り)を持ち、やる気のある日は倍(20語+文法2課)学べる。
   先取りした場合、翌日の通常配信は自然に復習になる。
   新出が尽きたら先頭から復習に回る(review: true)。 */
const PER_DAY = 5;
const enDays = Math.ceil(EN.length / PER_DAY);
const idDays = Math.ceil(ID.length / PER_DAY);
// 全単語が一巡しきるまでの日数を7の倍数に切り上げ(最低180日)
const TOTAL_DAYS = Math.max(180, Math.ceil(Math.max(enDays, idDays) / 7) * 7);

function wordsForDay(list, dayCount, d) {
  const idx = (d - 1) % dayCount;
  return {
    review: d > dayCount,
    list: list.slice(idx * PER_DAY, idx * PER_DAY + PER_DAY).map(toObj),
  };
}
function grammarForDay(d) {
  const gLang = d % 2 === 1 ? 'en' : 'id';
  const seq = Math.floor((d - 1) / 2);
  const lessons = GRAMMAR[gLang];
  const lesson = lessons[seq % lessons.length];
  return {
    lang: gLang,
    no: (seq % lessons.length) + 1,
    review: seq >= lessons.length,
    title: lesson.t,
    point: lesson.e,
    examples: lesson.ex.map(e => ({ text: e[0], jp: e[1] })),
  };
}
function contentForDay(d) {
  return {
    words: { en: wordsForDay(EN, enDays, d), id: wordsForDay(ID, idDays, d) },
    grammar: grammarForDay(d),
  };
}

const days = [];
for (let d = 1; d <= TOTAL_DAYS; d++) {
  days.push({
    day: d,
    week: Math.floor((d - 1) / 7) + 1,
    theme: ROADMAP[Math.min(11, Math.floor((d - 1) / 7))][0],
    ...contentForDay(d),
    extra: contentForDay(d + 1), // やる気のある日の追加分(翌日の先取り)
  });
}

const curriculum = {
  app: 'MIGNON LINGO',
  updated: new Date().toISOString().slice(0, 10),
  note: 'LINEボット配信用カリキュラム(180日)。day 1 の日付(start_date)はボット側で保持し、経過日数で days[] を引く。extra はその日の追加学習分(翌日の先取り。先取りした翌日は同内容が復習として流れる)。90日は最初のマイルストーンで、学習は継続する。',
  per_day: { words: PER_DAY * 2, grammar: 1, with_extra: { words: PER_DAY * 4, grammar: 2 } },
  days,
};
writeFileSync(new URL('./curriculum.json', import.meta.url), JSON.stringify(curriculum), 'utf8');

console.log(`words.json:      en=${words.en.length} id=${words.id.length} weeks=${words.roadmap.length}`);
console.log(`curriculum.json: days=${days.length} (en new until day ${enDays}, id until day ${idDays}, grammar new until day ${GRAMMAR.en.length + GRAMMAR.id.length})`);

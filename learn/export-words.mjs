// index.html 内の単語データを words.json に書き出すスクリプト。
// 単語データの正本は index.html。単語を追加・変更したら必ず再実行すること:
//   node learn/export-words.mjs
import { readFileSync, writeFileSync } from 'fs';

const htmlPath = new URL('./index.html', import.meta.url);
const html = readFileSync(htmlPath, 'utf8');

function grab(name) {
  const m = html.match(new RegExp('const ' + name + ' = (\\[[\\s\\S]*?\\n\\]);'));
  if (!m) throw new Error(name + ' not found in index.html');
  return eval(m[1]);
}

const toObj = w => ({ word: w[0], meaning: w[1], category: w[2], ...(w[3] ? { forms: w[3] } : {}) });

const out = {
  app: 'MIGNON LINGO',
  updated: new Date().toISOString().slice(0, 10),
  note: '英語×インドネシア語 90日集中プログラムの単語データ。LINEボット等の外部ツールが読む用。',
  roadmap: grab('ROADMAP').map((r, i) => ({ week: i + 1, theme: r[0], goal: r[1] })),
  en: grab('EN_WORDS').map(toObj),
  id: grab('ID_WORDS').map(toObj),
};

writeFileSync(new URL('./words.json', import.meta.url), JSON.stringify(out, null, 1), 'utf8');
console.log(`words.json written: en=${out.en.length} id=${out.id.length} weeks=${out.roadmap.length}`);

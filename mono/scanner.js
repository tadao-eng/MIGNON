// バーコード読取。
// ブラウザ標準の BarcodeDetector API を優先し、非対応環境(iOS Safari 等)では
// zxing-js(CDN から遅延ロード)にフォールバックする。
// フォールバック時は低レベルAPI + TRY_HARDER + 自前の90度回転走査により、
// 縦向き・逆向きのバーコードにも対応する
// (0/180度は TRY_HARDER の反転走査、90/270度はcanvas回転で拾う)。

const ZXING_URL = 'https://unpkg.com/@zxing/library@0.21.3/umd/index.min.js';
const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code'];
const SCAN_INTERVAL_MS = 250;
const MAX_DECODE_SIZE = 1024;

let zxingLoading = null;

function loadZXing() {
  if (window.ZXing) return Promise.resolve();
  if (!zxingLoading) {
    zxingLoading = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = ZXING_URL;
      s.onload = resolve;
      s.onerror = () => {
        zxingLoading = null;
        reject(new Error('読取ライブラリを取得できませんでした(オフライン?)'));
      };
      document.head.appendChild(s);
    });
  }
  return zxingLoading;
}

function buildZXingHints(ZXing) {
  const hints = new Map();
  hints.set(ZXing.DecodeHintType.TRY_HARDER, true);
  hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
    ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8,
    ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E,
    ZXing.BarcodeFormat.CODE_128, ZXing.BarcodeFormat.CODE_39,
    ZXing.BarcodeFormat.ITF, ZXing.BarcodeFormat.QR_CODE,
  ]);
  return hints;
}

/**
 * バーコードのスキャンを開始する。
 * @param {HTMLVideoElement} video プレビュー表示先
 * @param {(code: string) => void} onResult 最初に読み取れた値で1回呼ばれる
 * @param {(msg: string) => void} onStatus 状態表示用
 * @returns {Promise<{stop: () => void}>}
 */
export async function startScan(video, onResult, onStatus) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('この環境ではカメラを利用できません(HTTPSが必要です)');
  }

  let stopped = false;
  let done = false;
  const emit = (code) => {
    if (done || !code) return;
    done = true;
    onResult(code);
  };

  if ('BarcodeDetector' in window) {
    // --- ネイティブAPI ---
    const supported = await window.BarcodeDetector.getSupportedFormats().catch(() => []);
    const formats = FORMATS.filter((f) => supported.includes(f));
    const detector = new window.BarcodeDetector(formats.length ? { formats } : undefined);

    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
    onStatus('バーコードを枠に合わせてください');

    const timer = setInterval(async () => {
      if (stopped || done || video.readyState < 2) return;
      try {
        const codes = await detector.detect(video);
        if (codes.length) emit(codes[0].rawValue);
      } catch { /* フレーム取得失敗は無視して次のフレームへ */ }
    }, SCAN_INTERVAL_MS);

    return {
      stop() {
        stopped = true;
        clearInterval(timer);
        stream.getTracks().forEach((t) => t.stop());
        video.srcObject = null;
      },
    };
  }

  // --- zxing-js フォールバック ---
  onStatus('読取ライブラリを読み込んでいます…');
  await loadZXing();
  const ZXing = window.ZXing;

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width: { ideal: 1280 } },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();

  const stopStream = () => {
    stream.getTracks().forEach((t) => t.stop());
    video.srcObject = null;
  };

  if (!ZXing.HTMLCanvasElementLuminanceSource) {
    // 保険: UMDのバージョン差異で低レベルAPIが無い場合は従来経路(回転走査なし)にフォールバック
    const reader = new ZXing.BrowserMultiFormatReader(buildZXingHints(ZXing));
    await reader.decodeFromVideoDevice(null, video, (result) => {
      if (result) emit(result.getText());
    });
    onStatus('バーコードを枠に合わせてください(縦向きでもOK)');

    return {
      stop() {
        stopped = true;
        reader.reset();
        stopStream();
      },
    };
  }

  // 低レベルAPI: 毎フレーム、通常canvas → 90度回転canvas の順に判定する。
  // 90度回転させることで縦向きのバーコードも拾える(TRY_HARDERの反転走査と合わせて
  // 0/90/180/270度いずれの向きでも読み取れる)。
  const mfReader = new ZXing.MultiFormatReader();
  mfReader.setHints(buildZXingHints(ZXing));

  function decodeCanvas(canvas) {
    const source = new ZXing.HTMLCanvasElementLuminanceSource(canvas);
    const bitmap = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(source));
    return mfReader.decode(bitmap); // 見つからない場合は NotFoundException を投げる
  }

  // ループ外で使い回す作業用canvas(毎tick生成しない)
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const rotated = document.createElement('canvas');
  const rctx = rotated.getContext('2d');

  const timer = setInterval(() => {
    if (stopped || done || video.readyState < 2) return;
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) return;

    const scale = Math.min(1, MAX_DECODE_SIZE / Math.max(vw, vh));
    const w = Math.max(1, Math.round(vw * scale));
    const h = Math.max(1, Math.round(vh * scale));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    ctx.drawImage(video, 0, 0, w, h);

    try {
      const result = decodeCanvas(canvas);
      if (result) {
        emit(result.getText());
        return;
      }
    } catch { /* NotFoundException等は回転させて再試行 */ }
    if (done) return;

    // 90度回転させた版でも試す(縦向きバーコード対策)
    if (rotated.width !== h || rotated.height !== w) {
      rotated.width = h;
      rotated.height = w;
    }
    rctx.setTransform(1, 0, 0, 1, 0, 0);
    rctx.translate(h, 0);
    rctx.rotate(Math.PI / 2);
    rctx.drawImage(canvas, 0, 0);

    try {
      const result = decodeCanvas(rotated);
      if (result) emit(result.getText());
    } catch { /* NotFoundException等は次のtickへ */ }
  }, SCAN_INTERVAL_MS);

  onStatus('バーコードを枠に合わせてください(縦向きでもOK)');

  return {
    stop() {
      stopped = true;
      clearInterval(timer);
      stopStream();
    },
  };
}

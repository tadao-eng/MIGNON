// バーコード読取。
// ブラウザ標準の BarcodeDetector API を優先し、非対応環境(iOS Safari 等)では
// zxing-js(CDN から遅延ロード)にフォールバックする。

const ZXING_URL = 'https://unpkg.com/@zxing/library@0.21.3/umd/index.min.js';
const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code'];

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
    }, 250);

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
  const reader = new window.ZXing.BrowserMultiFormatReader();
  await reader.decodeFromVideoDevice(null, video, (result) => {
    if (result) emit(result.getText());
  });
  onStatus('バーコードを枠に合わせてください');

  return {
    stop() {
      stopped = true;
      reader.reset();
    },
  };
}

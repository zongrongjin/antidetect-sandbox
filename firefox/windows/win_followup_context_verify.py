import json
import http.server
import os
import sys
import tempfile
import threading

sys.path.insert(0, r"D:\bc")
import browser_controller as bc

FIREFOX = r"D:\ff\obj-release\dist\bin\firefox.exe"
PAGE_PORT = 9334


class ProbeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><meta charset=utf-8><title>followup</title>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def profile(font, voice, texture, samples, precision, policy):
    shader = {
        "35633:36338": precision,
        "35632:36338": precision,
    }
    return {
        "fontFamilies": [font],
        "fontAliases": {
            "ContextAlias": "Arial" if voice == "Voice Alpha" else "Courier New",
            "system-ui": "Arial" if voice == "Voice Alpha" else "Courier New",
        },
        "outerWidth": 1400 if voice == "Voice Alpha" else 1500,
        "outerHeight": 900 if voice == "Voice Alpha" else 902,
        "cssMedia": {
            "colorGamut": "p3" if voice == "Voice Alpha" else "srgb",
            "dynamicRange": "high" if voice == "Voice Alpha" else "standard",
            "prefersContrast": "more" if voice == "Voice Alpha" else "no-preference",
            "prefersReducedMotion": "reduce" if voice == "Voice Alpha" else "no-preference",
            "forcedColors": "active" if voice == "Voice Alpha" else "none",
        },
        "mediaCodecs": {
            "canPlayType": {
                "video/x-context": "probably" if voice == "Voice Alpha" else "maybe"
            },
            "mediaSource": ["video/x-context"] if voice == "Voice Alpha" else [],
            "decodingInfo": {
                'video/webm; codecs="vp8"': {
                    "supported": voice == "Voice Alpha",
                    "smooth": voice == "Voice Alpha",
                    "powerEfficient": False,
                },
            },
        },
        "mediaDevices": [{
            "kind": "audioinput" if voice == "Voice Alpha" else "videoinput",
            "label": voice + " Device",
            "deviceId": "alpha-id" if voice == "Voice Alpha" else "beta-id",
            "groupId": "alpha-group" if voice == "Voice Alpha" else "beta-group",
        }],
        "speechVoices": [{
            "name": voice,
            "lang": "en-US",
            "voiceURI": "urn:fp:" + voice,
            "localService": True,
            "default": True,
        }],
        "webglParameters": {
            "3379": {"type": "int", "value": texture},
        },
        "webgl2Parameters": {
            "36183": {"type": "int", "value": samples},
        },
        "webglShaderPrecision": shader,
        "webgl2ShaderPrecision": shader,
        "webRTC": policy,
    }


PROBE = r"""
(async () => {
  const out = {
    alpha: document.fonts.check('12px FpAlphaOnly'),
    beta: document.fonts.check('12px FpBetaOnly'),
    aliasWidth: null,
    systemWidth: null,
    arialWidth: null,
    courierWidth: null,
    voices: speechSynthesis.getVoices().map(v => ({
      name: v.name, lang: v.lang, uri: v.voiceURI,
      local: v.localService, def: v.default
    })),
    plugins: Array.from(navigator.plugins, p => p.name),
    mimeTypes: Array.from(navigator.mimeTypes, m => m.type),
    pdfViewerEnabled: navigator.pdfViewerEnabled,
    webgl: null,
    webgl2: null,
    outer: [outerWidth, outerHeight],
    css: {
      p3: matchMedia('(color-gamut: p3)').matches,
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      contrast: matchMedia('(prefers-contrast: more)').matches,
      hdr: matchMedia('(dynamic-range: high)').matches,
      forced: matchMedia('(forced-colors: active)').matches,
    },
    codecs: {
      custom: document.createElement('video').canPlayType('video/x-context'),
      mseCustom: MediaSource.isTypeSupported('video/x-context'),
      mseOther: MediaSource.isTypeSupported('video/x-other'),
    },
  };
  out.decoding = await navigator.mediaCapabilities.decodingInfo({
    type: 'file',
    video: {
      contentType: 'video/webm; codecs="vp8"',
      width: 640, height: 360, bitrate: 500000, framerate: 30
    }
  }).then(x => ({
    supported: x.supported, smooth: x.smooth,
    powerEfficient: x.powerEfficient
  }));
  const measure = font => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.font = `24px "${font}"`;
    return ctx.measureText('MWil1 fingerprint').width;
  };
  out.aliasWidth = measure('ContextAlias');
  out.systemWidth = measure('system-ui');
  out.arialWidth = measure('Arial');
  out.courierWidth = measure('Courier New');
  out.workerFont = await new Promise((resolve, reject) => {
    const source = `
      onmessage = () => {
        const canvas = new OffscreenCanvas(300, 100);
        const ctx = canvas.getContext('2d');
        const width = font => {
          ctx.font = '24px "' + font + '"';
          return ctx.measureText('MWil1 fingerprint').width;
        };
        postMessage({
          aliasWidth: width('ContextAlias'),
          systemWidth: width('system-ui'),
          arialWidth: width('Arial'),
          courierWidth: width('Courier New')
        });
      };`;
    const worker = new Worker(URL.createObjectURL(
      new Blob([source], {type: 'text/javascript'})));
    worker.onmessage = event => {
      worker.terminate();
      resolve(event.data);
    };
    worker.onerror = reject;
    worker.postMessage(null);
  });
  const c1 = document.createElement('canvas');
  const g1 = c1.getContext('webgl');
  if (g1) {
    const p = g1.getShaderPrecisionFormat(g1.VERTEX_SHADER, g1.HIGH_FLOAT);
    out.webgl = {
      texture: g1.getParameter(g1.MAX_TEXTURE_SIZE),
      precision: [p.rangeMin, p.rangeMax, p.precision]
    };
  }
  const c2 = document.createElement('canvas');
  const g2 = c2.getContext('webgl2');
  if (g2) {
    const p = g2.getShaderPrecisionFormat(g2.VERTEX_SHADER, g2.HIGH_FLOAT);
    out.webgl2 = {
      samples: g2.getParameter(g2.MAX_SAMPLES),
      precision: [p.rangeMin, p.rangeMax, p.precision]
    };
  }
  const devices = await Promise.race([
    navigator.mediaDevices.enumerateDevices(),
    new Promise(resolve => setTimeout(() => resolve(null), 5000))
  ]);
  out.devicesTimedOut = devices === null;
  out.devices = devices ? devices.map(d => ({
    kind: d.kind, label: d.label, deviceId: d.deviceId, groupId: d.groupId
  })) : [];
  return JSON.stringify(out);
})()
"""


def read(context):
    context.get(f"http://127.0.0.1:{PAGE_PORT}/")
    return json.loads(context.run_js_async(PROBE))


def main():
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", PAGE_PORT), ProbeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = bc.launch(
        FIREFOX,
        port=9333,
        profile=tempfile.mkdtemp(prefix="ff-p0-", dir=r"D:\temp"),
        timeout=90,
        extra_args=["-headless"],
    )
    contexts = []
    try:
        a = root.new_context(
            fingerprint=profile(
                "FpAlphaOnly", "Voice Alpha", 12345, 2, [31, 30, 17], 0
            )
        )
        contexts.append(a)
        b = root.new_context(
            fingerprint=profile(
                "FpBetaOnly", "Voice Beta", 23456, 8, [63, 62, 15], 2
            )
        )
        contexts.append(b)
        native = root.new_context()
        contexts.append(native)

        result = {
            "a": read(a),
            "b": read(b),
            "native": read(native),
            "a_after_b": read(a),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))

        assert result["a"]["alpha"] and not result["a"]["beta"]
        assert result["b"]["beta"] and not result["b"]["alpha"]
        assert result["a"]["voices"][0]["name"] == "Voice Alpha"
        assert result["b"]["voices"][0]["name"] == "Voice Beta"
        assert result["a"]["aliasWidth"] == result["a"]["arialWidth"]
        assert result["b"]["aliasWidth"] == result["b"]["courierWidth"]
        assert result["a"]["systemWidth"] == result["a"]["arialWidth"]
        assert result["b"]["systemWidth"] == result["b"]["courierWidth"]
        assert result["a"]["aliasWidth"] != result["b"]["aliasWidth"]
        assert (
            result["a"]["workerFont"]["aliasWidth"] ==
            result["a"]["workerFont"]["arialWidth"]
        )
        assert (
            result["b"]["workerFont"]["aliasWidth"] ==
            result["b"]["workerFont"]["courierWidth"]
        )
        assert result["a"]["outer"] == [1400, 900]
        assert result["b"]["outer"] == [1500, 902]
        assert result["a"]["css"] == {
            "p3": True, "reduced": True, "contrast": True, "hdr": True,
            "forced": True,
        }
        assert result["b"]["css"] == {
            "p3": False, "reduced": False, "contrast": False, "hdr": False,
            "forced": False,
        }
        assert result["a"]["codecs"] == {
            "custom": "probably", "mseCustom": True, "mseOther": False,
        }
        assert result["b"]["codecs"] == {
            "custom": "maybe", "mseCustom": False, "mseOther": False,
        }
        assert result["a"]["decoding"] == {
            "supported": True, "smooth": True, "powerEfficient": False,
        }
        assert result["b"]["decoding"] == {
            "supported": False, "smooth": False, "powerEfficient": False,
        }
        assert not result["a"]["devicesTimedOut"]
        assert not result["b"]["devicesTimedOut"]
        assert result["a"]["devices"][0]["label"] == "Voice Alpha Device"
        assert result["b"]["devices"][0]["label"] == "Voice Beta Device"
        assert result["a_after_b"] == result["a"]
        if result["a"]["webgl"] is not None:
            assert result["a"]["webgl"]["texture"] == 12345
            assert result["b"]["webgl"]["texture"] == 23456
            assert result["a"]["webgl"]["precision"] == [31, 30, 17]
            assert result["b"]["webgl"]["precision"] == [63, 62, 15]
        if result["a"]["webgl2"] is not None:
            assert result["a"]["webgl2"]["samples"] == 2
            assert result["b"]["webgl2"]["samples"] == 8
        print("FIREFOX_P0_CONTEXT_ISOLATION_OK")
    finally:
        server.shutdown()
        for context in reversed(contexts):
            try:
                context.close()
            except Exception:
                pass
        root.close()


if __name__ == "__main__":
    main()

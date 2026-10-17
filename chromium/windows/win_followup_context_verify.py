import json
import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from websocket import create_connection


CHROME = r"D:\src\src\out\Default\chrome.exe"
PROFILE = r"D:\browser_todo_backup\chromium_p0_verify_profile"
PORT = 9231
PAGE_PORT = 9232
NEXT_ID = 0


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


def call(ws, method, params=None, session_id=None):
    global NEXT_ID
    NEXT_ID += 1
    request = {"id": NEXT_ID, "method": method, "params": params or {}}
    if session_id:
        request["sessionId"] = session_id
    ws.send(json.dumps(request))
    while True:
        response = json.loads(ws.recv())
        if response.get("id") != NEXT_ID:
            continue
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        return response.get("result", {})


def wait_debugger():
    url = f"http://127.0.0.1:{PORT}/json/version"
    for _ in range(160):
        try:
            return json.load(urllib.request.urlopen(url, timeout=1))
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Chrome DevTools endpoint did not start")


PROBE = r"""(async () => {
  const rtcCandidates = await new Promise(async resolve => {
    const pc = new RTCPeerConnection();
    const candidates = [];
    pc.onicecandidate = event => {
      if (event.candidate) {
        candidates.push({
          candidate: event.candidate.candidate,
          type: event.candidate.type,
          address: event.candidate.address,
        });
      } else {
        pc.close();
        resolve(candidates);
      }
    };
    pc.createDataChannel('probe');
    await pc.setLocalDescription(await pc.createOffer());
    setTimeout(() => {
      pc.close();
      resolve(candidates);
    }, 3000);
  });
  const c1 = document.createElement('canvas');
  const gl1 = c1.getContext('webgl');
  const c2 = document.createElement('canvas');
  const gl2 = c2.getContext('webgl2');
  const precision = gl1 && gl1.getShaderPrecisionFormat(
    gl1.FRAGMENT_SHADER, gl1.HIGH_FLOAT);
  const extensions = gl1 ? gl1.getSupportedExtensions() : [];
  const measure = font => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.font = `24px "${font}"`;
    return ctx.measureText('MWil1 fingerprint').width;
  };
  const workerFont = await new Promise((resolve, reject) => {
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
  return JSON.stringify({
    rtcCandidates,
    arial: document.fonts.check('16px Arial'),
    courier: document.fonts.check('16px "Courier New"'),
    aliasWidth: measure('ContextAlias'),
    arialWidth: measure('Arial'),
    courierWidth: measure('Courier New'),
    workerFont,
    voices: speechSynthesis.getVoices().map(v => ({
      name:v.name, lang:v.lang, uri:v.voiceURI,
      local:v.localService, def:v.default
    })),
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
    decoding: await navigator.mediaCapabilities.decodingInfo({
      type: 'file',
      video: {
        contentType: 'video/webm; codecs="vp8"',
        width: 640, height: 360, bitrate: 500000, framerate: 30
      }
    }).then(x => ({
      supported: x.supported, smooth: x.smooth,
      powerEfficient: x.powerEfficient
    })),
    devices: (await navigator.mediaDevices.enumerateDevices()).map(d => ({
      kind: d.kind, label: d.label, deviceId: d.deviceId, groupId: d.groupId
    })),
    maxTexture1: gl1 && gl1.getParameter(gl1.MAX_TEXTURE_SIZE),
    maxTexture2: gl2 && gl2.getParameter(gl2.MAX_TEXTURE_SIZE),
    maxSamples: gl2 && gl2.getParameter(gl2.MAX_SAMPLES),
    precision: precision && [
      precision.rangeMin, precision.rangeMax, precision.precision
    ],
    extensions,
    extensionObjectsAgree: extensions.every(x => gl1.getExtension(x) !== null)
  });
})()"""


def create_context(ws, profile):
    context = call(ws, "Target.createBrowserContext")["browserContextId"]
    target = call(ws, "Target.createTarget", {
        "url": "about:blank", "browserContextId": context,
    })["targetId"]
    session = call(ws, "Target.attachToTarget", {
        "targetId": target, "flatten": True,
    })["sessionId"]
    if profile is not None:
        call(ws, "Fingerprint.setContextOverrides", {
            "fingerprint": json.dumps(profile),
        }, session)
    call(ws, "Page.enable", session_id=session)
    call(ws, "Page.navigate", {
        "url": f"http://127.0.0.1:{PAGE_PORT}/",
    }, session)
    time.sleep(0.5)
    return context, target, session


def evaluate(ws, session):
    result = call(ws, "Runtime.evaluate", {
        "expression": PROBE, "returnByValue": True, "awaitPromise": True,
    }, session)
    value = result["result"]["value"]
    return json.loads(value) if isinstance(value, str) else value


def main():
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", PAGE_PORT), ProbeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    shutil.rmtree(PROFILE, ignore_errors=True)
    os.makedirs(PROFILE, exist_ok=True)
    process = subprocess.Popen([
        CHROME,
        f"--user-data-dir={PROFILE}",
        f"--remote-debugging-port={PORT}",
        "--remote-allow-origins=*",
        "--headless=new",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu-sandbox",
        "--use-gl=angle",
        "--use-angle=swiftshader-webgl",
        "--enable-unsafe-swiftshader",
        "--no-sandbox",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        version = wait_debugger()
        ws = create_connection(version["webSocketDebuggerUrl"], timeout=20)
        common = {
            "webglExtensions": [
                "OES_texture_float", "WEBGL_debug_renderer_info",
                "__not_a_real_extension__",
            ],
        }
        profile_a = {
            **common,
            "webRTC": 0,
            "fontFamilies": ["Arial"],
            "fontAliases": {
                "ContextAlias": "Arial",
                "system-ui": "Arial",
            },
            "outerWidth": 1401,
            "outerHeight": 901,
            "cssMedia": {
                "colorGamut": "p3", "dynamicRange": "high",
                "prefersContrast": "more", "prefersReducedMotion": "reduce",
                "forcedColors": "active",
            },
            "mediaCodecs": {
                "canPlayType": {"video/x-context": "probably"},
                "mediaSource": ["video/x-context"],
                "decodingInfo": {
                    'video/webm; codecs="vp8"': {
                        "supported": True, "smooth": True,
                        "powerEfficient": False,
                    },
                },
            },
            "mediaDevices": [{
                "kind": "audioinput", "label": "Context A Microphone",
                "deviceId": "ctx-a-mic", "groupId": "ctx-a-group",
            }],
            "speechVoices": [{
                "name": "Context A", "lang": "en-US",
                "voiceURI": "ctx-a", "localService": True, "default": True,
            }],
            "webglParameters": {
                "3379": {"type": "int", "value": 12345},
            },
            "webgl2Parameters": {
                "3379": {"type": "int", "value": 12345},
                "36183": {"type": "int", "value": 2},
            },
            "webglShaderPrecision": {
                "35632:36338": [-99, 99, 17],
            },
        }
        profile_b = {
            **common,
            "fontFamilies": ["Courier New"],
            "fontAliases": {
                "ContextAlias": "Courier New",
                "system-ui": "Courier New",
            },
            "outerWidth": 1502,
            "outerHeight": 902,
            "cssMedia": {
                "colorGamut": "srgb", "dynamicRange": "standard",
                "prefersContrast": "no-preference",
                "prefersReducedMotion": "no-preference",
                "forcedColors": "none",
            },
            "mediaCodecs": {
                "canPlayType": {"video/x-context": "maybe"},
                "mediaSource": [],
                "decodingInfo": {
                    'video/webm; codecs="vp8"': {
                        "supported": False, "smooth": False,
                        "powerEfficient": False,
                    },
                },
            },
            "mediaDevices": [{
                "kind": "videoinput", "label": "Context B Camera",
                "deviceId": "ctx-b-cam", "groupId": "ctx-b-group",
            }],
            "speechVoices": [{
                "name": "Context B", "lang": "fr-FR",
                "voiceURI": "ctx-b", "localService": False, "default": True,
            }],
            "webglParameters": {
                "3379": {"type": "int", "value": 23456},
            },
            "webgl2Parameters": {
                "3379": {"type": "int", "value": 23456},
                "36183": {"type": "int", "value": 8},
            },
            "webglShaderPrecision": {
                "35632:36338": [-88, 88, 15],
            },
        }
        ca, ta, sa = create_context(ws, profile_a)
        cb, tb, sb = create_context(ws, profile_b)
        cn, tn, sn = create_context(ws, None)
        a1, b, native, a2 = (
            evaluate(ws, sa), evaluate(ws, sb),
            evaluate(ws, sn), evaluate(ws, sa),
        )
        print(json.dumps({
            "chrome": version.get("Browser"),
            "a1": a1, "b": b, "native": native, "a2": a2,
        }, ensure_ascii=False, indent=2))
        assert a1 == a2
        assert a1["rtcCandidates"] == []
        assert native["rtcCandidates"]
        assert a1["arial"] and not a1["courier"]
        assert b["courier"] and not b["arial"]
        assert a1["aliasWidth"] == a1["arialWidth"]
        assert b["aliasWidth"] == b["courierWidth"]
        assert a1["aliasWidth"] != b["aliasWidth"]
        assert a1["workerFont"]["aliasWidth"] == a1["workerFont"]["arialWidth"]
        assert b["workerFont"]["aliasWidth"] == b["workerFont"]["courierWidth"]
        assert a1["workerFont"]["systemWidth"] == a1["workerFont"]["arialWidth"]
        assert b["workerFont"]["systemWidth"] == b["workerFont"]["courierWidth"]
        assert a1["outer"] == [1401, 901]
        assert b["outer"] == [1502, 902]
        assert a1["css"] == {
            "p3": True, "reduced": True, "contrast": True, "hdr": True,
            "forced": True,
        }
        assert b["css"] == {
            "p3": False, "reduced": False, "contrast": False, "hdr": False,
            "forced": False,
        }
        assert a1["codecs"] == {
            "custom": "probably", "mseCustom": True, "mseOther": False,
        }
        assert b["codecs"] == {
            "custom": "maybe", "mseCustom": False, "mseOther": False,
        }
        assert a1["decoding"] == {
            "supported": True, "smooth": True, "powerEfficient": False,
        }
        assert b["decoding"] == {
            "supported": False, "smooth": False, "powerEfficient": False,
        }
        assert a1["devices"][0]["label"] == "Context A Microphone"
        assert b["devices"][0]["label"] == "Context B Camera"
        assert a1["voices"][0]["name"] == "Context A"
        assert b["voices"][0]["name"] == "Context B"
        assert a1["maxTexture1"] == a1["maxTexture2"] == 12345
        assert b["maxTexture1"] == b["maxTexture2"] == 23456
        assert a1["maxSamples"] == 2 and b["maxSamples"] == 8
        assert a1["precision"] == [-99, 99, 17]
        assert b["precision"] == [-88, 88, 15]
        assert a1["extensionObjectsAgree"] and b["extensionObjectsAgree"]
        assert "__not_a_real_extension__" not in a1["extensions"]
        assert native["maxTexture1"] not in (12345, 23456)
        print("CHROMIUM_P0_CONTEXT_ISOLATION_OK")
    finally:
        server.shutdown()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()

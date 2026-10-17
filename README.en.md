# Anti-Detect Sandbox

[English](README.en.md) · [中文](README.md)

Kernel patches for **Chromium** and **Firefox**. The core:

1. **Isolated contexts**: many environments in one process, so concurrency costs less memory; fingerprint and egress proxy can be switched per environment.
2. **Custom responses + custom cache**: the kernel can control any request. Serve in-memory HTML as an HTTP response; static assets and fetch requests unrelated to the job HIT cache or are dropped by rule. Less network, faster loads, less traffic.

This repo ships patches and scripts only, not a full browser tree. It is for authorized security research, anti-detect research, and privacy testing.

```
antidetect-sandbox/
  chromium/    Chromium 151.0.7907.0 · CDP Context.setContextOverrides
  firefox/     Firefox 152.0.5        · BiDi moz:context.setContextOverrides
```

| | [chromium/](chromium/README.md) | [firefox/](firefox/README.md) |
|---|---|---|
| Base version | 151.0.7907.0 (commit `fdadfe85`) | 152.0.5 official tarball |
| Protocol | CDP `Context.setContextOverrides` | BiDi `moz:context.setContextOverrides` |
| Isolation unit | `BrowserContext` | `userContext` / `BrowsingContext` |
| Prebuilt | [Latest Release](https://github.com/zongrongjin/antidetect-sandbox/releases/latest) Windows mini_installer | [Latest Release](https://github.com/zongrongjin/antidetect-sandbox/releases/latest) Windows installer |
| Kasada demo | `chromium/scripts/kasada_demo.py` | `firefox/scripts/kasada_demo.py` |

Each engine has extra patches of its own — Chromium brand consistency, Gecko `webdriver` / `isTrusted`, and similar.

---

## 1. Isolated contexts: cheaper concurrency, switchable fingerprint and proxy

Stock Chrome / Firefox, and the usual commercial fingerprint browsers (AdsPower / Multilogin / GoLogin / Dolphin{anty} and similar), are **one environment per process**: one identity is one browser process (or one isolated profile). N identities means N processes, so under high concurrency memory and startup cost grow linearly with the number of jobs.

The isolation unit here is a **context** (Chromium `BrowserContext`, Firefox `userContext` / `BrowsingContext`):

- **One process, many environments.** Pages, cookie jar, cache, proxy, and fingerprint are bound to the context and do not leak across. Concurrent jobs share one browser process — what you save is process-level GPU / network stack / code pages, not another full browser clone.
- **Fingerprint and proxy travel with the context and can be switched.** A new profile and a new egress IP are one `setContextOverrides`. No browser restart, no new process.
- The main page, iframes, cross-origin OOPIFs, and dedicated / shared / service workers inherit the same context state, so fingerprint stays consistent inside that context.

The fingerprint is a JSON profile on that context (UA, platform, language, timezone, screen, hardwareConcurrency, WebGL, WebRTC public IP, fonts, canvas/audio readback, …). Fields are optional; omit to keep native.

The proxy is on the same command: credentials travel with the endpoint. The kernel sends `Proxy-Authorization` up front.

---

## 2. Custom responses + custom cache: less traffic, faster loads

The live homepage and repeat JS/CSS/images do not need to go through the residential proxy every time. These two patches sit in the network stack:

| | What it does | What you get |
|---|---|---|
| **`url` + `html` custom response** | Address bar is the target URL; body is HTML in memory, served as an HTTP replacement (Chromium camouflaged as live HTTP/1.1; Firefox `nsIReplacedHttpResponse`) | The first document need not touch the network. Scripts in that HTML load as you specify. |
| **Custom cache** | HIT / block / pass by URL rule. A HIT is fulfilled by the kernel | Repeat assets at zero RTT; telemetry can be blocked. Traffic and wait time both drop. |

Cookies go into that context’s jar only. Cache rules, the fake home, cookies, fingerprint, and proxy are all part of the same command.

---

## What it is for

- Several isolated environments in one process (for example Windows desktop + Android), fingerprint and egress IP bound together. Switching identity does not start a new process.
- Precise traffic control: fake home as an HTTP response, cache HIT on repeats, so research / regression burns less bandwidth and waits less on the network.
- **WAF / CAPTCHA** research: put the challenge or captcha entry script in the fake home, HIT static assets, let decision requests go out.

---

## How to use it against antibot

Against Kasada / PerimeterX / DataDome, fake HTML and custom cache go out on the same `setContextOverrides`. Build the smallest HTML that can pass the target site, send telemetry from a real browser environment, and collect the credentials the WAF issues.

Against Turnstile / HCaptcha / FunCaptcha, pick a minimal captcha-frontend demo for the risk level and pass it over CDP. Or load the original page, put static assets and unrelated requests in cache, and only pass captcha-related requests to get a high score.

**Fake HTML (`url` + `html`)**: the address bar is the target URL; the body is the minimal HTML you built; the kernel serves it as an HTTP response. Keep only the entry script. You do not need to fetch the live homepage. The SDK loads via `<script src>` and POSTs to the matching path.

**Custom cache**: only the decision POSTs should leave the machine. HIT the entry script and static assets (css, fonts, images) so residential-proxy traffic and RTT are not spent re-downloading the same script ten times. Block telemetry / ads / beacons. Pass key requests such as `/tl`, `/collector`, `/js/` — those must use this context’s proxy and profile. Cache does not pass the check for you.

The path is: issue fingerprint + proxy on the context → load the fake home (HIT static, block beacons) → SDK collects → decision request goes out.

Worked Kasada example: `chromium/scripts/kasada_demo.py`, `firefox/scripts/kasada_demo.py`. The fake home injects `/p.js`, waits for `/tl`, and passes when the body contains `reload`.

---

## Comparison

| | Commercial patched browsers | Environment spoofing | This repo |
|---|---|---|---|
| Maintenance | Hard to pass risk checks at concurrency | Every JS update means a new environment patch | Profile lives in the kernel, antibot JS updates do not force a chase; patch C++ only when a read point is missing |
| Machine resources | One identity per process (fingerprint browsers too) | Lowest: only V8 / isolated-vm / vm2 and similar | Many contexts in one process |
| Proxy traffic | First document and static assets go through the proxy every time | Only core requests hit the network | Same as spoofing: only necessary requests leave |
| Speed | Cold start every identity; full page over the network | Only fetch and compute what the target risk check needs; no JS/CSS render | Same as spoofing, plus baseline browser cost |

Ordinary automation opens the browser and clicks; environment spoofing uses Node to fool the risk SDK; commercial fingerprint browsers give one profile per process; this stack is many switchable contexts in one process, with first document and cache in the kernel so you hit the network less. Passing a WAF still needs a consistent profile and a clean egress IP. The kernel is not a universal solution.

---

## How to use it

1. Get a patched binary (Chromium Release assets, or build from each engine README).
2. Open the remote debugging port (Chromium CDP / Firefox BiDi).
3. **Create an isolated context** (do not pass stock `proxyServer` at create time).
4. Send **one** `setContextOverrides` to that context (fingerprint, proxy, cookies, cache, optional first document together).
5. Navigate, click, and run scripts as usual.
6. To switch identity: send another overrides, or open another context. Do not restart the process.

The shape is the same; only the method and session model change:

```python
profile = {
    "userAgent": "...",          # Chrome 151 or Firefox 152 — match the engine
    "platform": "Win32",
    "timezone": "America/New_York",
    "webglVendor": "Google Inc. (NVIDIA)",
    "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "webRTC": 0,
}

overrides = {
    "fingerprint": json.dumps(profile),
    "proxy": {"endpoint": "host:port", "username": "...", "password": "..."},
    "cookies": [{"name": "a", "value": "b", "domain": "example.com", "path": "/"}],
    "cache": {"dir": "", "map": "{}", "rules": json.dumps({"blocks": ["*/telemetry/*"]})},
    "url": "https://example.com/",
    "html": "<!doctype html>...",   # optional; with url = in-memory first document
}

# Chromium (page session already attached to that BrowserContext)
cdp("Context.setContextOverrides", overrides)

# Firefox (after BiDi session.new)
overrides["userContexts"] = [user_context_id]
bidi("moz:context.setContextOverrides", overrides)
```

`fingerprint` must be a **JSON string**. Do not flatten profile fields onto the protocol params.

**Kasada (Arc'teryx)** is the worked example: the custom response injects `/p.js`, waits for `/tl`, and passes only if the body contains `reload`. Proxy comes from the environment; the script never prints ct/h.

```bash
export KASADA_PROXY='http://user:pass@host:port'   # US/CA residential
python3 chromium/scripts/kasada_demo.py /path/to/chrome
python3 firefox/scripts/kasada_demo.py /path/to/firefox
```

Builds, full field lists, and Windows notes:

- Chromium: [chromium/README.md](chromium/README.md) · fields [chromium/docs/SPECIAL-CDP.md](chromium/docs/SPECIAL-CDP.md)
- Firefox: [firefox/README.md](firefox/README.md) · fields [firefox/docs/FINGERPRINT-SCHEMA.md](firefox/docs/FINGERPRINT-SCHEMA.md)

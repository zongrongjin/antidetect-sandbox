"""Minimal Fingerprint serializer for Chromium_zzbrowser CDP JSON."""

from __future__ import annotations

import json


_SNAKE_TO_CAMEL = {
    "user_agent": "userAgent",
    "ua_full_brands": "uaFullBrands",
    "ua_brands": "uaBrands",
    "platform_version": "platformVersion",
    "hardware_concurrency": "hardwareConcurrency",
    "accept_languages": "acceptLanguages",
    "screen_width": "screenWidth",
    "screen_height": "screenHeight",
    "avail_width": "availWidth",
    "avail_height": "availHeight",
    "avail_left": "availLeft",
    "avail_top": "availTop",
    "color_depth": "colorDepth",
    "device_memory": "deviceMemory",
    "max_touch_points": "maxTouchPoints",
    "webgl_vendor": "webglVendor",
    "webgl_renderer": "webglRenderer",
    "webgl_extensions": "webglExtensions",
    "webgl2_extensions": "webgl2Extensions",
    "readback_seed": "readbackSeed",
    "outer_width": "outerWidth",
    "outer_height": "outerHeight",
    "viewport_width": "viewportWidth",
    "viewport_height": "viewportHeight",
    "pdf_viewer_enabled": "pdfViewerEnabled",
    "mime_types": "mimeTypes",
    "css_media": "cssMedia",
    "ua_platform": "uaPlatform",
    "form_factors": "formFactors",
}


def _brand_pair(item):
    if not isinstance(item, dict):
        return item
    if "b" in item and "v" in item:
        return {"b": item["b"], "v": item["v"]}
    brand = item.get("brand") or item.get("b")
    version = item.get("version") or item.get("v")
    return {"b": brand, "v": version}


def _major(version):
    if version is None:
        return version
    return str(version).split(".", 1)[0]


class Fingerprint:
    def __init__(self, **kwargs):
        self._raw = dict(kwargs)
        ua = kwargs.get("user_agent") or ""
        mobile = bool(kwargs.get("mobile"))
        if "ua_platform" not in kwargs and "uaPlatform" not in kwargs:
            if mobile or "Android" in ua:
                self._raw["ua_platform"] = "Android"
            elif "Macintosh" in ua:
                self._raw["ua_platform"] = "macOS"
            elif "Windows" in ua:
                self._raw["ua_platform"] = "Windows"
            elif "Linux" in ua or "X11" in ua:
                self._raw["ua_platform"] = "Linux"
        if "platform" not in kwargs:
            ua_platform = self._raw.get("ua_platform") or self._raw.get("uaPlatform")
            if ua_platform == "Android":
                self._raw["platform"] = "Linux armv81"
            elif ua_platform == "macOS":
                self._raw["platform"] = "MacIntel"
            elif ua_platform == "Windows":
                self._raw["platform"] = "Win32"
            elif ua_platform == "Linux":
                self._raw["platform"] = "Linux x86_64"
            elif ua_platform == "iOS":
                self._raw["platform"] = "iPhone"

    def to_cdp(self):
        out = {}
        for key, value in self._raw.items():
            if value is None:
                continue
            if key in ("font_families", "font_aliases", "speech_voices",
                       "media_codecs", "media_devices", "webgl_parameters",
                       "webgl2_parameters", "webgl_shader_precision",
                       "webgl2_shader_precision", "webgpu",
                       "product_capabilities"):
                continue
            ckey = _SNAKE_TO_CAMEL.get(key, key)
            if key in ("ua_full_brands", "ua_brands"):
                value = [_brand_pair(x) for x in value]
            out[ckey] = value
        if "uaFullBrands" in out and "uaBrands" not in out:
            out["uaBrands"] = [
                {"b": x["b"], "v": _major(x.get("v"))} for x in out["uaFullBrands"]
            ]
        return out

    def dumps(self):
        return json.dumps(self.to_cdp(), ensure_ascii=False)

    def __repr__(self):
        return "Fingerprint(%s)" % self.dumps()[:120]

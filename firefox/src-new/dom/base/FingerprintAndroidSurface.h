/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_FingerprintAndroidSurface_h
#define mozilla_dom_FingerprintAndroidSurface_h

// BROWSER_FINGERPRINT_ANDROID_SURFACE
// Shared JSON helpers for plugins / pdfViewerEnabled / connection. Keyboard
// API is not implemented by real Firefox, so there is nothing to hide.

#include "mozilla/Maybe.h"
#include "mozilla/dom/BrowsingContext.h"
#include "nsPIDOMWindow.h"
#include "nsString.h"

namespace mozilla::dom::fp_android_surface {

inline bool FindKeyValue(const nsAString& aJson, const char* aKey,
                         uint32_t& aValuePos) {
  nsAutoString pat;
  pat.Append(char16_t('"'));
  pat.AppendASCII(aKey);
  pat.Append(char16_t('"'));
  const char16_t* d = aJson.BeginReading();
  const char16_t* p = pat.BeginReading();
  uint32_t n = aJson.Length();
  uint32_t pl = pat.Length();
  for (uint32_t i = 0; i + pl <= n; ++i) {
    bool match = true;
    for (uint32_t j = 0; j < pl; ++j) {
      if (d[i + j] != p[j]) {
        match = false;
        break;
      }
    }
    if (!match) {
      continue;
    }
    uint32_t k = i + pl;
    while (k < n && (d[k] == char16_t(' ') || d[k] == char16_t('\t'))) {
      ++k;
    }
    if (k >= n || d[k] != char16_t(':')) {
      continue;
    }
    ++k;
    while (k < n && (d[k] == char16_t(' ') || d[k] == char16_t('\t'))) {
      ++k;
    }
    if (k >= n) {
      continue;
    }
    aValuePos = k;
    return true;
  }
  return false;
}

inline bool StartsWithASCII(const nsAString& aJson, uint32_t aPos,
                            const char* aLit) {
  uint32_t n = aJson.Length();
  for (uint32_t i = 0; aLit[i]; ++i) {
    if (aPos + i >= n || aJson[aPos + i] != char16_t(aLit[i])) {
      return false;
    }
  }
  return true;
}

inline bool ExtractStr(const nsAString& aJson, const char* aKey,
                       nsAString& aOut) {
  uint32_t pos;
  if (!FindKeyValue(aJson, aKey, pos) || aJson[pos] != char16_t('"')) {
    return false;
  }
  uint32_t start = pos + 1;
  uint32_t end = start;
  uint32_t n = aJson.Length();
  while (end < n && aJson[end] != char16_t('"')) {
    ++end;
  }
  aOut = Substring(aJson, start, end - start);
  return true;
}

inline bool IsEmptyArray(const nsAString& aJson, const char* aKey) {
  uint32_t pos;
  if (!FindKeyValue(aJson, aKey, pos) || aJson[pos] != char16_t('[')) {
    return false;
  }
  uint32_t k = pos + 1;
  uint32_t n = aJson.Length();
  while (k < n && (aJson[k] == char16_t(' ') || aJson[k] == char16_t('\t'))) {
    ++k;
  }
  return k < n && aJson[k] == char16_t(']');
}

inline bool IsFalse(const nsAString& aJson, const char* aKey) {
  uint32_t pos;
  return FindKeyValue(aJson, aKey, pos) && StartsWithASCII(aJson, pos, "false");
}

inline bool IsTrue(const nsAString& aJson, const char* aKey) {
  uint32_t pos;
  return FindKeyValue(aJson, aKey, pos) && StartsWithASCII(aJson, pos, "true");
}

inline bool IsObject(const nsAString& aJson, const char* aKey) {
  uint32_t pos;
  return FindKeyValue(aJson, aKey, pos) && aJson[pos] == char16_t('{');
}

inline bool GetJson(nsPIDOMWindowInner* aWindow, nsAString& aJson) {
  aJson.Truncate();
  if (!aWindow) {
    return false;
  }
  BrowsingContext* bc = aWindow->GetBrowsingContext();
  if (!bc) {
    return false;
  }
  aJson = bc->Top()->GetFingerprintProfile();
  return !aJson.IsEmpty();
}

inline bool ContainsASCII(const nsAString& aHay, const char* aNeedle) {
  nsAutoString needle;
  needle.AssignASCII(aNeedle);
  return aHay.Find(needle) >= 0;
}

inline bool IsAndroid(const nsAString& aJson) {
  nsAutoString ua;
  nsAutoString plat;
  ExtractStr(aJson, "userAgent", ua);
  ExtractStr(aJson, "platform", plat);
  return ContainsASCII(ua, "Android") || ContainsASCII(plat, "Android");
}

inline bool IsIOS(const nsAString& aJson) {
  nsAutoString ua;
  nsAutoString plat;
  ExtractStr(aJson, "userAgent", ua);
  ExtractStr(aJson, "platform", plat);
  return ContainsASCII(ua, "iPhone") || ContainsASCII(ua, "iPad") ||
         ContainsASCII(ua, "iPod") || plat.EqualsLiteral("iPhone") ||
         plat.EqualsLiteral("iPad");
}

// Empty plugins array wins. Non-empty list is ignored (native 5 PDF, no
// half-plugin objects). Missing key + Android/iOS UA → empty.
inline bool ForceEmptyPlugins(const nsAString& aJson) {
  uint32_t pos;
  if (FindKeyValue(aJson, "plugins", pos)) {
    return IsEmptyArray(aJson, "plugins");
  }
  return IsAndroid(aJson) || IsIOS(aJson);
}

inline Maybe<bool> PdfViewerOverride(const nsAString& aJson) {
  if (IsTrue(aJson, "pdfViewerEnabled")) {
    return Some(true);
  }
  if (IsFalse(aJson, "pdfViewerEnabled")) {
    return Some(false);
  }
  if (IsAndroid(aJson) || IsIOS(aJson)) {
    return Some(true);
  }
  return Nothing();
}

enum class ConnVis { Native, Hide, Show };

// connection===false or iOS default → hide (attribute absent).
// connection object or Android default → show (Android Firefox has the API).
// else native pref (desktop Firefox: hidden).
inline ConnVis ConnectionVisibility(const nsAString& aJson) {
  uint32_t pos;
  if (FindKeyValue(aJson, "connection", pos)) {
    if (StartsWithASCII(aJson, pos, "false")) {
      return ConnVis::Hide;
    }
    if (aJson[pos] == char16_t('{')) {
      return ConnVis::Show;
    }
  }
  if (IsIOS(aJson)) {
    return ConnVis::Hide;
  }
  if (IsAndroid(aJson)) {
    return ConnVis::Show;
  }
  return ConnVis::Native;
}

inline bool ExtractConnField(const nsAString& aJson, const char* aField,
                             nsAString& aOut) {
  uint32_t pos;
  if (!FindKeyValue(aJson, "connection", pos) || aJson[pos] != char16_t('{')) {
    return false;
  }
  int depth = 0;
  uint32_t end = pos;
  uint32_t n = aJson.Length();
  for (; end < n; ++end) {
    if (aJson[end] == char16_t('{')) {
      ++depth;
    } else if (aJson[end] == char16_t('}')) {
      --depth;
      if (depth == 0) {
        ++end;
        break;
      }
    }
  }
  nsDependentSubstring obj(aJson, pos, end - pos);
  return ExtractStr(obj, aField, aOut);
}

// Firefox Network Information only exposes ConnectionType. Map Chromium-shaped
// connection objects onto wifi/cellular when possible.
inline Maybe<nsCString> ConnectionTypeToken(const nsAString& aJson) {
  nsAutoString type;
  if (ExtractConnField(aJson, "type", type)) {
    NS_ConvertUTF16toUTF8 utf(type);
    return Some(nsCString(utf));
  }
  nsAutoString ect;
  if (ExtractConnField(aJson, "effectiveType", ect)) {
    if (ect.EqualsLiteral("4g") || ect.EqualsLiteral("3g") ||
        ect.EqualsLiteral("2g") || ect.EqualsLiteral("slow-2g")) {
      return Some("cellular"_ns);
    }
  }
  if (IsAndroid(aJson)) {
    return Some("wifi"_ns);
  }
  return Nothing();
}

}  // namespace mozilla::dom::fp_android_surface

#endif  // mozilla_dom_FingerprintAndroidSurface_h

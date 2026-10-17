"""随机指纹画像：ua + region → 完整自洽指纹。

用法::

    from browser_controller import Profile

    p = Profile("chrome", "us")       # Chrome + 美国 + Windows
    p = Profile("firefox", "jp")      # Firefox + 日本
    p = Profile(None, "us", os="android")  # Android + Chrome
    p = Profile("chrome", "de", version="150")  # 显式兼容旧大版本

    print(p.fingerprint)              # Fingerprint 实例
    print(p.engine)                   # "chrome" / "firefox"

region 支持：国家代码（us/gb/de/jp/kr/es/fr/br/au/...）→ 自动派生
timezone、locale、accept_languages。

随机维度（自洽）：
- UA 小版本号（同大版本内随机）
- 屏幕分辨率（按平台加权随机）
- GPU（按平台+时代加权随机）
- hardware_concurrency（合理范围加权随机）
- platform_version（Windows build / macOS 小版本）
"""

import random
import re

from fingerprint import Fingerprint


# ── 地区数据 ──


def _region(tz, locale, *extra_languages):
    """构造地区语言序列，保证 navigator.language 与 Intl locale 首项一致。"""
    languages = [locale]
    base_language = locale.split("-", 1)[0]
    if base_language != locale:
        languages.append(base_language)
    languages.extend(extra_languages)
    if base_language != "en":
        languages.append("en")
    return {
        "tz": tz,
        "locale": locale,
        "langs": ",".join(dict.fromkeys(languages)),
    }


# ISO 3166-1 alpha-2（另含常用 xk）到一个主流本地画像。多时区国家选择人口密集地区，
# 不尝试根据代理城市猜城市级时区；调用方若有精确位置仍可直接覆盖 timezone。
_REGIONS = {
    "ad": _region("Europe/Andorra", "ca-AD"),
    "ae": _region("Asia/Dubai", "ar-AE"),
    "af": _region("Asia/Kabul", "fa-AF"),
    "ag": _region("America/Antigua", "en-AG"),
    "al": _region("Europe/Tirane", "sq-AL"),
    "am": _region("Asia/Yerevan", "hy-AM"),
    "ao": _region("Africa/Luanda", "pt-AO"),
    "ar": _region("America/Argentina/Buenos_Aires", "es-AR"),
    "as": _region("Pacific/Pago_Pago", "en-AS"),
    "at": _region("Europe/Vienna", "de-AT"),
    "au": _region("Australia/Sydney", "en-AU"),
    "aw": _region("America/Aruba", "nl-AW"),
    "az": _region("Asia/Baku", "az-AZ"),
    "ba": _region("Europe/Sarajevo", "bs-BA"),
    "bb": _region("America/Barbados", "en-BB"),
    "bd": _region("Asia/Dhaka", "bn-BD"),
    "be": _region("Europe/Brussels", "nl-BE"),
    "bf": _region("Africa/Ouagadougou", "fr-BF"),
    "bg": _region("Europe/Sofia", "bg-BG"),
    "bh": _region("Asia/Bahrain", "ar-BH"),
    "bi": _region("Africa/Bujumbura", "fr-BI"),
    "bj": _region("Africa/Porto-Novo", "fr-BJ"),
    "bm": _region("Atlantic/Bermuda", "en-BM"),
    "bn": _region("Asia/Brunei", "ms-BN"),
    "bo": _region("America/La_Paz", "es-BO"),
    "br": _region("America/Sao_Paulo", "pt-BR"),
    "bs": _region("America/Nassau", "en-BS"),
    "bt": _region("Asia/Thimphu", "dz-BT"),
    "bw": _region("Africa/Gaborone", "en-BW"),
    "by": _region("Europe/Minsk", "be-BY"),
    "bz": _region("America/Belize", "en-BZ"),
    "ca": _region("America/Toronto", "en-CA"),
    "cd": _region("Africa/Kinshasa", "fr-CD"),
    "cf": _region("Africa/Bangui", "fr-CF"),
    "cg": _region("Africa/Brazzaville", "fr-CG"),
    "ch": _region("Europe/Zurich", "de-CH"),
    "ci": _region("Africa/Abidjan", "fr-CI"),
    "cl": _region("America/Santiago", "es-CL"),
    "cm": _region("Africa/Douala", "fr-CM"),
    "cn": _region("Asia/Shanghai", "zh-CN"),
    "co": _region("America/Bogota", "es-CO"),
    "cr": _region("America/Costa_Rica", "es-CR"),
    "cu": _region("America/Havana", "es-CU"),
    "cv": _region("Atlantic/Cape_Verde", "pt-CV"),
    "cy": _region("Asia/Nicosia", "el-CY"),
    "cz": _region("Europe/Prague", "cs-CZ"),
    "de": _region("Europe/Berlin", "de-DE"),
    "dj": _region("Africa/Djibouti", "fr-DJ"),
    "dk": _region("Europe/Copenhagen", "da-DK"),
    "dm": _region("America/Dominica", "en-DM"),
    "do": _region("America/Santo_Domingo", "es-DO"),
    "dz": _region("Africa/Algiers", "ar-DZ"),
    "ec": _region("America/Guayaquil", "es-EC"),
    "ee": _region("Europe/Tallinn", "et-EE"),
    "eg": _region("Africa/Cairo", "ar-EG"),
    "es": _region("Europe/Madrid", "es-ES"),
    "et": _region("Africa/Addis_Ababa", "am-ET"),
    "fi": _region("Europe/Helsinki", "fi-FI"),
    "fj": _region("Pacific/Fiji", "en-FJ"),
    "fo": _region("Atlantic/Faroe", "fo-FO"),
    "fr": _region("Europe/Paris", "fr-FR"),
    "ga": _region("Africa/Libreville", "fr-GA"),
    "gb": _region("Europe/London", "en-GB"),
    "gd": _region("America/Grenada", "en-GD"),
    "ge": _region("Asia/Tbilisi", "ka-GE"),
    "gf": _region("America/Cayenne", "fr-GF"),
    "gg": _region("Europe/Guernsey", "en-GG"),
    "gh": _region("Africa/Accra", "en-GH"),
    "gi": _region("Europe/Gibraltar", "en-GI"),
    "gl": _region("America/Nuuk", "kl-GL"),
    "gm": _region("Africa/Banjul", "en-GM"),
    "gn": _region("Africa/Conakry", "fr-GN"),
    "gp": _region("America/Guadeloupe", "fr-GP"),
    "gq": _region("Africa/Malabo", "es-GQ"),
    "gr": _region("Europe/Athens", "el-GR"),
    "gt": _region("America/Guatemala", "es-GT"),
    "gu": _region("Pacific/Guam", "en-GU"),
    "gy": _region("America/Guyana", "en-GY"),
    "hk": _region("Asia/Hong_Kong", "zh-HK"),
    "hn": _region("America/Tegucigalpa", "es-HN"),
    "hr": _region("Europe/Zagreb", "hr-HR"),
    "ht": _region("America/Port-au-Prince", "fr-HT"),
    "hu": _region("Europe/Budapest", "hu-HU"),
    "id": _region("Asia/Jakarta", "id-ID"),
    "ie": _region("Europe/Dublin", "en-IE"),
    "il": _region("Asia/Jerusalem", "he-IL"),
    "im": _region("Europe/Isle_of_Man", "en-IM"),
    "in": _region("Asia/Kolkata", "en-IN", "hi-IN", "hi"),
    "iq": _region("Asia/Baghdad", "ar-IQ"),
    "ir": _region("Asia/Tehran", "fa-IR"),
    "is": _region("Atlantic/Reykjavik", "is-IS"),
    "it": _region("Europe/Rome", "it-IT"),
    "je": _region("Europe/Jersey", "en-JE"),
    "jm": _region("America/Jamaica", "en-JM"),
    "jo": _region("Asia/Amman", "ar-JO"),
    "jp": _region("Asia/Tokyo", "ja-JP"),
    "ke": _region("Africa/Nairobi", "en-KE"),
    "kg": _region("Asia/Bishkek", "ky-KG"),
    "kh": _region("Asia/Phnom_Penh", "km-KH"),
    "ki": _region("Pacific/Tarawa", "en-KI"),
    "km": _region("Indian/Comoro", "fr-KM"),
    "kn": _region("America/St_Kitts", "en-KN"),
    "kr": _region("Asia/Seoul", "ko-KR"),
    "kw": _region("Asia/Kuwait", "ar-KW"),
    "ky": _region("America/Cayman", "en-KY"),
    "kz": _region("Asia/Almaty", "kk-KZ"),
    "la": _region("Asia/Vientiane", "lo-LA"),
    "lb": _region("Asia/Beirut", "ar-LB"),
    "lc": _region("America/St_Lucia", "en-LC"),
    "li": _region("Europe/Vaduz", "de-LI"),
    "lk": _region("Asia/Colombo", "si-LK"),
    "lr": _region("Africa/Monrovia", "en-LR"),
    "ls": _region("Africa/Maseru", "en-LS"),
    "lt": _region("Europe/Vilnius", "lt-LT"),
    "lu": _region("Europe/Luxembourg", "fr-LU"),
    "lv": _region("Europe/Riga", "lv-LV"),
    "ly": _region("Africa/Tripoli", "ar-LY"),
    "ma": _region("Africa/Casablanca", "ar-MA"),
    "mc": _region("Europe/Monaco", "fr-MC"),
    "md": _region("Europe/Chisinau", "ro-MD"),
    "me": _region("Europe/Podgorica", "sr-ME"),
    "mg": _region("Indian/Antananarivo", "mg-MG"),
    "mh": _region("Pacific/Majuro", "en-MH"),
    "mk": _region("Europe/Skopje", "mk-MK"),
    "ml": _region("Africa/Bamako", "fr-ML"),
    "mm": _region("Asia/Yangon", "my-MM"),
    "mn": _region("Asia/Ulaanbaatar", "mn-MN"),
    "mo": _region("Asia/Macau", "zh-MO"),
    "mp": _region("Pacific/Saipan", "en-MP"),
    "mq": _region("America/Martinique", "fr-MQ"),
    "mr": _region("Africa/Nouakchott", "ar-MR"),
    "mt": _region("Europe/Malta", "mt-MT"),
    "mu": _region("Indian/Mauritius", "en-MU"),
    "mv": _region("Indian/Maldives", "dv-MV"),
    "mw": _region("Africa/Blantyre", "en-MW"),
    "mx": _region("America/Mexico_City", "es-MX"),
    "my": _region("Asia/Kuala_Lumpur", "ms-MY"),
    "mz": _region("Africa/Maputo", "pt-MZ"),
    "na": _region("Africa/Windhoek", "en-NA"),
    "nc": _region("Pacific/Noumea", "fr-NC"),
    "ne": _region("Africa/Niamey", "fr-NE"),
    "ng": _region("Africa/Lagos", "en-NG"),
    "ni": _region("America/Managua", "es-NI"),
    "nl": _region("Europe/Amsterdam", "nl-NL"),
    "no": _region("Europe/Oslo", "nb-NO"),
    "np": _region("Asia/Kathmandu", "ne-NP"),
    "nr": _region("Pacific/Nauru", "en-NR"),
    "nz": _region("Pacific/Auckland", "en-NZ"),
    "om": _region("Asia/Muscat", "ar-OM"),
    "pa": _region("America/Panama", "es-PA"),
    "pe": _region("America/Lima", "es-PE"),
    "pf": _region("Pacific/Tahiti", "fr-PF"),
    "pg": _region("Pacific/Port_Moresby", "en-PG"),
    "ph": _region("Asia/Manila", "en-PH"),
    "pk": _region("Asia/Karachi", "ur-PK"),
    "pl": _region("Europe/Warsaw", "pl-PL"),
    "pr": _region("America/Puerto_Rico", "es-PR"),
    "ps": _region("Asia/Hebron", "ar-PS"),
    "pt": _region("Europe/Lisbon", "pt-PT"),
    "pw": _region("Pacific/Palau", "en-PW"),
    "py": _region("America/Asuncion", "es-PY"),
    "qa": _region("Asia/Qatar", "ar-QA"),
    "re": _region("Indian/Reunion", "fr-RE"),
    "ro": _region("Europe/Bucharest", "ro-RO"),
    "rs": _region("Europe/Belgrade", "sr-RS"),
    "ru": _region("Europe/Moscow", "ru-RU"),
    "rw": _region("Africa/Kigali", "rw-RW"),
    "sa": _region("Asia/Riyadh", "ar-SA"),
    "sb": _region("Pacific/Guadalcanal", "en-SB"),
    "sc": _region("Indian/Mahe", "en-SC"),
    "sd": _region("Africa/Khartoum", "ar-SD"),
    "se": _region("Europe/Stockholm", "sv-SE"),
    "sg": _region("Asia/Singapore", "en-SG"),
    "si": _region("Europe/Ljubljana", "sl-SI"),
    "sk": _region("Europe/Bratislava", "sk-SK"),
    "sl": _region("Africa/Freetown", "en-SL"),
    "sm": _region("Europe/San_Marino", "it-SM"),
    "sn": _region("Africa/Dakar", "fr-SN"),
    "so": _region("Africa/Mogadishu", "so-SO"),
    "sr": _region("America/Paramaribo", "nl-SR"),
    "ss": _region("Africa/Juba", "en-SS"),
    "st": _region("Africa/Sao_Tome", "pt-ST"),
    "sv": _region("America/El_Salvador", "es-SV"),
    "sy": _region("Asia/Damascus", "ar-SY"),
    "sz": _region("Africa/Mbabane", "en-SZ"),
    "td": _region("Africa/Ndjamena", "fr-TD"),
    "tg": _region("Africa/Lome", "fr-TG"),
    "th": _region("Asia/Bangkok", "th-TH"),
    "tj": _region("Asia/Dushanbe", "tg-TJ"),
    "tl": _region("Asia/Dili", "pt-TL"),
    "tm": _region("Asia/Ashgabat", "tk-TM"),
    "tn": _region("Africa/Tunis", "ar-TN"),
    "to": _region("Pacific/Tongatapu", "to-TO"),
    "tr": _region("Europe/Istanbul", "tr-TR"),
    "tt": _region("America/Port_of_Spain", "en-TT"),
    "tw": _region("Asia/Taipei", "zh-TW"),
    "tz": _region("Africa/Dar_es_Salaam", "sw-TZ"),
    "ua": _region("Europe/Kyiv", "uk-UA"),
    "ug": _region("Africa/Kampala", "en-UG"),
    "us": _region("America/New_York", "en-US"),
    "uy": _region("America/Montevideo", "es-UY"),
    "uz": _region("Asia/Tashkent", "uz-UZ"),
    "va": _region("Europe/Vatican", "it-VA"),
    "vc": _region("America/St_Vincent", "en-VC"),
    "ve": _region("America/Caracas", "es-VE"),
    "vg": _region("America/Tortola", "en-VG"),
    "vi": _region("America/St_Thomas", "en-VI"),
    "vn": _region("Asia/Ho_Chi_Minh", "vi-VN"),
    "vu": _region("Pacific/Efate", "en-VU"),
    "ws": _region("Pacific/Apia", "sm-WS"),
    "xk": _region("Europe/Belgrade", "sq-XK"),
    "ye": _region("Asia/Aden", "ar-YE"),
    "za": _region("Africa/Johannesburg", "en-ZA"),
    "zm": _region("Africa/Lusaka", "en-ZM"),
    "zw": _region("Africa/Harare", "en-ZW"),
}


def _pick_random_profile_value(choices):
    """画像显式传 random 时，从支持值中选择一个。"""
    return random.choice(tuple(choices))


def _accept_language_q(langs):
    """逗号分隔语言列表 → 带 q 值的 Accept-Language 串（对齐真实 Chrome 派生规则）。

    真实 Chrome 从 intl.accept_languages 列表派生请求头时，首项 q=1（省略不写），
    其后每项 q 递减 0.1：

        en-US,en          → en-US,en;q=0.9
        de-DE,de,en       → de-DE,de;q=0.9,en;q=0.8
        ko-KR,ko,en-US,en → ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7

    魔改浏览器的 setContextOverrides(acceptLanguages) 是把值逐字透传当请求头、自身不补 q，
    故在此按 Chrome 规则补上，避免 Akamai/TMX 等风控因裸列表（无 q）判为异常。
    （navigator.languages 由浏览器侧从该值解析，需魔改端剥掉 q 还原成列表。）
    """
    parts = [p.strip() for p in langs.split(",") if p.strip()]
    out = []
    for i, p in enumerate(parts):
        if i == 0:
            out.append(p)                      # 首项 q=1，省略
        else:
            tenths = 10 - i                    # 0.9, 0.8, 0.7 ...
            if tenths < 1:
                tenths = 1                     # 超长列表兜底（region 数据最多 4 项，用不到）
            out.append("%s;q=0.%d" % (p, tenths))
    return ",".join(out)

# 当前随节点发布的魔改浏览器版本，仅用于识别本机内核；Profile 默认仍按真实
# 版本池随机大版本/完整版本，调用方明确接受其与底层内核不完全一致。
CHROME_RUNTIME_VERSION = "151.0.7907.0"
FIREFOX_RUNTIME_VERSION = "152.0.5"

# ── Chrome 版本池（大版本 → 真实完整版本号，来源 Google 官方 versionhistory API）──
# 覆盖 120 → 最新(151, 2026-07)。大版本不在此范围时 _build_chrome 随机凑 build/patch。

# 每个大版本：(build 号固定, [多个真实 patch])。build 每个大版本唯一，patch 随机取真实值。
_CHROME_VERSIONS = {
    "151": ("7922", (34,)),
    "150": ("7871", (182, 181, 130, 129, 128, 127, 126, 125, 124, 116, 115, 114, 102, 101, 100, 49, 47, 46, 24)),
    "149": ("7827", (201, 200, 198, 196, 158, 156, 155, 116, 114, 104, 102, 55, 53, 22)),
    "148": ("7778", (218, 217, 216, 181, 179, 178, 169, 168, 167, 98, 97, 96, 56)),
    "147": ("7727", (139, 137, 119, 117, 116, 103, 101, 57, 55, 50, 49, 24)),
    "146": ("7680", (180, 178, 167, 165, 155, 153, 81, 80, 76, 75, 72, 71, 66, 65, 31)),
    "145": ("7632", (162, 160, 119, 117, 111, 109, 77, 75, 68, 46, 45, 26)),
    "144": ("7559", (135, 132, 112, 110, 98, 96, 61, 60, 59)),
    "143": ("7499", (194, 192, 171, 169, 148, 146, 111, 109, 42, 40)),
    "142": ("7444", (177, 175, 164, 162, 136, 135, 134, 61, 60, 59, 52)),
    "141": ("7390", (125, 122, 109, 107, 78, 76, 67, 65, 56, 54, 37)),
    "140": ("7339", (210, 208, 187, 185, 129, 127, 82, 80, 41)),
    "139": ("7258", (157, 155, 140, 138, 129, 127, 68, 67, 66)),
    "138": ("7204", (185, 183, 170, 168, 159, 157, 102, 100, 98, 97, 96, 51, 50, 49, 35)),
    "137": ("7151", (122, 119, 105, 103, 70, 68, 57, 55, 41, 40)),
    "136": ("7103", (116, 113, 94, 93, 92, 49, 48)),
    "135": ("7049", (117, 114, 97, 95, 86, 85, 84, 43, 42, 41)),
    "134": ("6998", (179, 177, 167, 165, 119, 118, 117, 90, 89, 88, 37, 36, 35)),
    "133": ("6943", (143, 142, 141, 128, 126, 100, 99, 98, 60, 59, 54, 53, 35)),
    "132": ("6834", (197, 196, 162, 160, 159, 112, 111, 110, 84, 83)),
    "131": ("6778", (267, 264, 206, 204, 141, 139, 110, 108, 87, 85, 71, 70, 69, 33)),
    "130": ("6723", (119, 116, 93, 91, 71, 70, 69, 60, 59, 58, 44)),
    "129": ("6668", (103, 100, 90, 72, 70, 60, 59, 58, 42)),
    "128": ("6613", (139, 137, 122, 120, 115, 113, 86, 84, 36)),
    "127": ("6533", (122, 119, 101, 99, 90, 88, 74, 72, 57)),
    "126": ("6478", (185, 182, 128, 116, 114, 63, 61, 57, 56, 36)),
    "125": ("6422", (176, 144, 141, 114, 78, 76, 61, 60, 41)),
    "124": ("6367", (210, 207, 203, 158, 155, 119, 93, 79, 63, 60)),
    "123": ("6312", (124, 122, 107, 88, 60, 58, 46)),
    "122": ("6261", (131, 128, 113, 96, 71, 69, 58, 39)),
    "121": ("6167", (189, 184, 162, 141, 139, 87, 75)),
    "120": ("6099", (227, 224, 218, 201, 129, 109, 72, 56)),
}

# ── Edge Stable 真实版本池（Microsoft Edge 官方 Stable release notes）──
#
# Edge 的产品版本 build 与 Chrome/Chromium build 不同，不能随机拼接。桌面和 Android
# 发布节奏/patch 也不同，因此分开采样；Chromium brand 仍从同大版本 Chrome 池取真实值。
_EDGE_DESKTOP_VERSIONS = {
    "150": ("4078", (105, 99, 96, 83, 80, 65, 50, 48)),
    "149": ("4022", (98, 96, 80, 69, 62, 52)),
    "148": ("3967", (137, 128, 118, 116, 109, 96, 83, 70, 54)),
    "147": ("3912", (98, 86, 72, 60)),
    "146": ("3856", (152, 139, 130, 117, 109, 97, 84, 78, 72, 62, 59)),
    "145": ("3800", (97, 82, 70, 65, 58)),
    "144": ("3719", (162, 151, 141, 130, 128, 115, 104, 92, 82)),
    "143": ("3650", (139, 96, 80, 75, 66)),
    "142": ("3595", (157, 136, 130, 120, 94, 90, 80, 76, 69, 65, 53)),
    "141": ("3537", (99, 92, 85, 71, 57)),
    "140": ("3485", (130, 119, 110, 94, 81, 66, 54)),
    "139": ("3405", (125, 119, 111, 102, 86)),
    "138": ("3351", (151, 144, 140, 132, 121, 109, 95, 83, 77, 65, 55)),
    "137": ("3296", (93, 83, 68, 62, 58, 52)),
    "136": ("3240", (131, 124, 115, 104, 92, 76, 64, 50)),
    "135": ("3179", (98, 85, 73, 66, 54)),
    "134": ("3124", (129, 119, 95, 93, 85, 83, 72, 68, 66, 62, 51)),
    "133": ("3065", (92, 82, 69, 59, 51)),
    "132": ("2957", (178, 171, 164, 158, 140, 127, 115)),
    "131": ("2903", (147, 146, 112, 99, 86, 70, 63, 51, 48)),
    "130": ("2849", (142, 123, 116, 108, 99, 80, 68, 56, 52, 46)),
    "129": ("2792", (89, 79, 65, 52)),
    "128": ("2739", (113, 107, 97, 90, 79, 67, 63, 54, 42)),
    "127": ("2651", (105, 98, 86, 74)),
    "126": ("2592", (137, 132, 113, 102, 87, 81, 68, 61, 56)),
    "125": ("2535", (92, 85, 79, 67, 51)),
    "124": ("2478", (131, 127, 121, 109, 105, 97, 80, 67, 51)),
    "123": ("2420", (97, 81, 65, 53)),
    "122": ("2365", (120, 113, 106, 92, 80, 66, 63, 59, 52)),
    "121": ("2277", (128, 112, 110, 106, 98, 83)),
    "120": ("2210", (181, 175, 167, 61)),
}

_EDGE_ANDROID_VERSIONS = {
    "150": ("4078", (96, 81, 65, 58, 50)),
    "149": ("4022", (105, 96, 80, 67, 53)),
    "148": ("3967", (97, 84, 70, 55)),
    "147": ("3912", (87, 77, 60)),
    "146": ("3856", (97, 85, 71, 62)),
    "145": ("3800", (99, 85)),
    "144": ("3719", (115, 103, 91, 81)),
    "143": ("3650", (139, 125, 112, 97, 88, 66)),
    "142": ("3595", (107, 93, 80, 66, 58)),
    "141": ("3537", (99, 91, 72)),
    "140": ("3485", (98, 81, 71, 52)),
    "139": ("3405", (125, 111, 102, 86)),
    "138": ("3351", (121, 109, 98, 83, 77, 66, 55)),
    "137": ("3296", (92, 82, 65, 53)),
    "136": ("3240", (91, 76, 64, 50)),
    "135": ("3179", (98, 85, 72, 54)),
    "134": ("3124", (105, 77, 68, 57)),
    "133": ("3065", (92, 80, 67, 54)),
    "132": ("2957", (129, 118)),
    "131": ("2903", (145, 134, 125, 113, 107, 101, 87, 77, 68, 48)),
    "130": ("2849", (80, 68, 57, 46)),
    "129": ("2792", (92, 84, 65, 58, 52, 50, 41, 31, 21, 12)),
    "128": ("2739", (82, 72, 64, 60)),
    "127": ("2651", (111, 102, 90, 82)),
    "126": ("2592", (117, 106, 100, 86, 80, 74, 56)),
    "125": ("2535", (96, 87, 72, 51)),
    "124": ("2478", (104, 87, 71, 62, 50)),
    "123": ("2420", (102, 90, 74, 61)),
    "122": ("2365", (99, 86, 76, 56)),
    "121": ("2277", (133, 105, 84)),
    "120": ("2210", (150, 141, 126, 116, 115, 105, 99, 86, 84, 78, 64, 59)),
}

# ── Firefox 版本池（大版本 → 多个真实完整版本，来源 Mozilla product-details）──
# 覆盖 120 → 最新(153, 2026-07)。每个大版本含 MAJOR.0 + 真实 dot 版本。

_FIREFOX_VERSIONS = {
    "153": ("153.0",),
    "152": ("152.0", "152.0.1", "152.0.2", "152.0.3", "152.0.4", "152.0.5", "152.0.6"),
    "151": ("151.0", "151.0.1", "151.0.2", "151.0.3", "151.0.4"),
    "150": ("150.0", "150.0.1", "150.0.2", "150.0.3"),
    "149": ("149.0", "149.0.2"),
    "148": ("148.0", "148.0.2"),
    "147": ("147.0", "147.0.1", "147.0.2", "147.0.3", "147.0.4"),
    "146": ("146.0", "146.0.1"),
    "145": ("145.0", "145.0.1", "145.0.2"),
    "144": ("144.0", "144.0.2"),
    "143": ("143.0", "143.0.1", "143.0.3", "143.0.4"),
    "142": ("142.0", "142.0.1"),
    "141": ("141.0", "141.0.2", "141.0.3"),
    "140": ("140.0", "140.0.1", "140.0.2", "140.0.4"),
    "139": ("139.0", "139.0.1", "139.0.4"),
    "138": ("138.0", "138.0.1", "138.0.3", "138.0.4"),
    "137": ("137.0", "137.0.1", "137.0.2"),
    "136": ("136.0", "136.0.1", "136.0.2", "136.0.3", "136.0.4"),
    "135": ("135.0", "135.0.1"),
    "134": ("134.0", "134.0.1", "134.0.2"),
    "133": ("133.0", "133.0.3"),
    "132": ("132.0", "132.0.1", "132.0.2"),
    "131": ("131.0", "131.0.2", "131.0.3"),
    "130": ("130.0", "130.0.1"),
    "129": ("129.0", "129.0.1", "129.0.2"),
    "128": ("128.0", "128.0.2", "128.0.3"),
    "127": ("127.0", "127.0.1", "127.0.2"),
    "126": ("126.0", "126.0.1"),
    "125": ("125.0", "125.0.1", "125.0.2", "125.0.3"),
    "124": ("124.0", "124.0.1", "124.0.2"),
    "123": ("123.0", "123.0.1"),
    "122": ("122.0", "122.0.1"),
    "121": ("121.0", "121.0.1"),
    "120": ("120.0", "120.0.1"),
}


def _pick_version_weighted(pool_keys) -> str:
    """从版本大版本号中加权随机选一个，偏向最新（真实用户分布偏新）。

    按版本从新到旧几何衰减：最新的权重最大。
    """
    majors = sorted(pool_keys, key=lambda x: int(x), reverse=True)
    weights = [0.7 ** i for i in range(len(majors))]
    return random.choices(majors, weights=weights, k=1)[0]

# ── 屏幕分辨率（platform → [(w, h, weight)] ）──

_SCREENS_WINDOWS = [
    (1920, 1080, 50),
    (2560, 1440, 20),
    (1366, 768, 15),
    (1536, 864, 8),
    (3840, 2160, 5),
    (1440, 900, 2),
]

_SCREENS_MAC = [
    (1920, 1080, 30),
    (2560, 1440, 25),
    (1440, 900, 20),
    (2560, 1600, 15),
    (3024, 1964, 5),
    (1680, 1050, 5),
]

_SCREENS_LINUX = [
    (1920, 1080, 60),
    (2560, 1440, 20),
    (1366, 768, 10),
    (3840, 2160, 10),
]

# 安卓 screen.width/height 报的是【CSS 逻辑像素】(= 物理 ÷ devicePixelRatio),不是物理分辨率。
# 每项 (CSS宽, CSS高, DPR, 权重),且 物理=CSS×DPR 自洽。
_SCREENS_ANDROID = [
    (360, 800, 3.0, 30),      # 物理 1080x2400  三星 A/S 中端,占比最大
    (412, 915, 2.625, 20),    # 物理 1080x2401  Pixel 6/7
    (393, 873, 2.75, 15),     # 物理 1080x2400  Pixel 8/9
    (360, 780, 3.0, 12),      # 物理 1080x2340
    (384, 854, 2.8125, 10),   # 物理 1080x2402  部分三星
    (412, 892, 3.5, 8),       # 物理 1442x3122  S23 Ultra 级
    (360, 640, 3.0, 5),       # 物理 1080x1920  老机型
]

# ── GPU 池（按平台）──

_GPU_WINDOWS = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)", 15),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)", 12),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)", 10),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)", 8),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)", 15),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)", 10),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", 12),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6600 XT Direct3D11 vs_5_0 ps_5_0, D3D11)", 8),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", 10),
]

_GPU_MAC = [
    ("Apple", "Apple M1", 25),
    ("Apple", "Apple M2", 25),
    ("Apple", "Apple M3", 20),
    ("Apple", "Apple M1 Pro", 15),
    ("Apple", "Apple M2 Pro", 10),
    ("Apple", "Apple M3 Pro", 5),
]

_GPU_LINUX = [
    ("Mesa", "Mesa Intel(R) UHD Graphics 630 (CFL GT2)", 30),
    ("Mesa", "Mesa Intel(R) Graphics (ADL GT2)", 25),
    ("NVIDIA Corporation", "NVIDIA GeForce RTX 3060/PCIe/SSE2", 20),
    ("NVIDIA Corporation", "NVIDIA GeForce GTX 1080/PCIe/SSE2", 15),
    ("AMD", "AMD Radeon RX 6700 XT (navi22, LLVM 15.0.7, DRM 3.49, 6.1.0-18-amd64)", 10),
]

_GPU_ANDROID = [
    ("Qualcomm", "Adreno (TM) 740", 16),        # 骁龙8Gen2 (S23)
    ("Qualcomm", "Adreno (TM) 730", 14),        # 骁龙8Gen1
    ("Qualcomm", "Adreno (TM) 750", 10),        # 骁龙8Gen3 (S24)
    ("Qualcomm", "Adreno (TM) 660", 9),         # 骁龙888
    ("Qualcomm", "Adreno (TM) 725", 5),         # 骁龙7Gen3
    ("Qualcomm", "Adreno (TM) 650", 4),         # 骁龙865
    ("Qualcomm", "Adreno (TM) 619", 3),         # 中端
    ("ARM", "Mali-G710 MC10", 8),               # Tensor G2 (Pixel 7)
    ("ARM", "Mali-G715 MC11", 7),               # Tensor G3 (Pixel 8)
    ("ARM", "Mali-G78 MC20", 5),                # Tensor G1 (Pixel 6)
    ("ARM", "Mali-G610 MC6", 4),                # Dimensity 8000/1080
    ("ARM", "Immortalis-G715 MC11", 3),         # Dimensity 9200
    ("ARM", "Immortalis-G720 MC12", 2),         # Dimensity 9300
    ("Samsung", "Xclipse 920", 2),              # Exynos 2200 (S22)
    ("Qualcomm", "Adreno (TM) 735", 2),         # 骁龙7+Gen2
]

# ── hardware_concurrency（按平台加权）──

_CORES_WINDOWS = [(4, 10), (6, 15), (8, 30), (12, 20), (16, 15), (24, 8), (32, 2)]
_CORES_MAC = [(8, 40), (10, 30), (12, 20), (16, 8), (24, 2)]
_CORES_LINUX = [(4, 15), (8, 35), (12, 20), (16, 20), (32, 8), (64, 2)]
_CORES_ANDROID = [(4, 10), (6, 15), (8, 65), (12, 10)]

# ── 跨 API 能力画像 ──
#
# 这些值与 GPU/OS 整机画像一起下发。浏览器端只在对应 JSON key 存在时覆盖；
# 手工构造 Fingerprint 且不传这些字段时仍走内核原生实现。

_FONT_FAMILIES = {
    "windows": [
        "Arial", "Calibri", "Cambria", "Candara", "Comic Sans MS",
        "Consolas", "Courier New", "Georgia", "Microsoft Sans Serif",
        "Segoe UI", "Segoe UI Emoji", "Segoe UI Symbol", "Tahoma",
        "Times New Roman", "Trebuchet MS", "Verdana",
    ],
    "mac": [
        "Arial", "Arial Hebrew", "Courier New", "Geneva", "Georgia",
        "Helvetica", "Helvetica Neue", "Hiragino Sans", "Menlo", "Monaco",
        "SF Pro Display", "SF Pro Text", "Times", "Times New Roman",
        "Apple Color Emoji",
    ],
    "linux": [
        "DejaVu Sans", "DejaVu Sans Mono", "DejaVu Serif", "Liberation Mono",
        "Liberation Sans", "Liberation Serif", "Noto Color Emoji",
        "Noto Sans", "Noto Serif", "Ubuntu", "Ubuntu Mono",
    ],
    "android": [
        "Droid Sans", "Noto Color Emoji", "Noto Sans", "Noto Serif",
        "Roboto", "Roboto Condensed", "sans-serif", "serif", "monospace",
    ],
}

_FONT_ALIASES = {
    "windows": {
        "system-ui": "Segoe UI", "sans-serif": "Arial",
        "serif": "Times New Roman", "monospace": "Consolas",
        "emoji": "Segoe UI Emoji",
    },
    "mac": {
        "system-ui": "SF Pro Text", "sans-serif": "Helvetica",
        "serif": "Times", "monospace": "Menlo",
        "emoji": "Apple Color Emoji",
    },
    "linux": {
        "system-ui": "Ubuntu", "sans-serif": "Ubuntu",
        "serif": "Noto Serif", "monospace": "Ubuntu Mono",
        "emoji": "Noto Color Emoji",
    },
    "android": {
        "system-ui": "Roboto", "sans-serif": "Roboto",
        "serif": "Noto Serif", "monospace": "monospace",
        "emoji": "Noto Color Emoji",
    },
}

_WINDOWS_VOICE_NAMES = {
    "en-US": ("Microsoft Zira", "Microsoft David"),
    "en-GB": ("Microsoft Hazel",),
    "de-DE": ("Microsoft Hedda",),
    "fr-FR": ("Microsoft Hortense",),
    "es-ES": ("Microsoft Helena",),
    "es-MX": ("Microsoft Sabina",),
    "it-IT": ("Microsoft Elsa",),
    "ja-JP": ("Microsoft Haruka",),
    "ko-KR": ("Microsoft Heami",),
    "zh-CN": ("Microsoft Huihui",),
    "zh-TW": ("Microsoft Hanhan",),
    "zh-HK": ("Microsoft Tracy",),
    "pt-BR": ("Microsoft Maria",),
    "en-IN": ("Microsoft Heera",),
    "ru-RU": ("Microsoft Irina",),
}

_MAC_VOICE_NAMES = {
    "en-US": ("Samantha", "Alex"),
    "en-GB": ("Daniel",),
    "en-AU": ("Karen",),
    "en-IN": ("Rishi",),
    "de-DE": ("Anna",),
    "fr-FR": ("Thomas",),
    "es-ES": ("Mónica",),
    "es-MX": ("Paulina",),
    "it-IT": ("Alice",),
    "ja-JP": ("Kyoko",),
    "ko-KR": ("Yuna",),
    "zh-CN": ("Tingting",),
    "zh-TW": ("Meijia",),
    "pt-BR": ("Luciana",),
    "ru-RU": ("Milena",),
}

# WebGL enum → {type, value}. 画像按可观察返回类型保存，避免把范围错误地
# 暴露成普通 Array（真实 API 对范围返回 Float32Array/Int32Array）。
_WEBGL_DESKTOP_PARAMETERS = {
    "3379": {"type": "int", "value": 16384},       # MAX_TEXTURE_SIZE
    "3386": {"type": "int32", "value": [32767, 32767]},  # MAX_VIEWPORT_DIMS
    "33901": {"type": "float32", "value": [1, 1024]},    # ALIASED_POINT_SIZE_RANGE
    "33902": {"type": "float32", "value": [1, 1]},       # ALIASED_LINE_WIDTH_RANGE
    "34076": {"type": "int", "value": 16384},      # MAX_CUBE_MAP_TEXTURE_SIZE
    "34921": {"type": "int", "value": 16},         # MAX_VERTEX_ATTRIBS
    "34930": {"type": "int", "value": 16},         # MAX_TEXTURE_IMAGE_UNITS
    "35660": {"type": "int", "value": 16},         # MAX_VERTEX_TEXTURE_IMAGE_UNITS
    "35661": {"type": "int", "value": 32},         # MAX_COMBINED_TEXTURE_IMAGE_UNITS
    "36347": {"type": "int", "value": 4096},       # MAX_VERTEX_UNIFORM_VECTORS
    "36348": {"type": "int", "value": 30},         # MAX_VARYING_VECTORS
    "36349": {"type": "int", "value": 1024},       # MAX_FRAGMENT_UNIFORM_VECTORS
}

_WEBGL_MOBILE_PARAMETERS = {
    **_WEBGL_DESKTOP_PARAMETERS,
    "3386": {"type": "int32", "value": [16384, 16384]},
    "33901": {"type": "float32", "value": [1, 1024]},
    "35661": {"type": "int", "value": 32},
    "36347": {"type": "int", "value": 1024},
    "36348": {"type": "int", "value": 15},
    "36349": {"type": "int", "value": 1024},
}

_WEBGL2_PARAMETERS = {
    "32883": {"type": "int", "value": 2048},       # MAX_3D_TEXTURE_SIZE
    "34852": {"type": "int", "value": 8},          # MAX_DRAW_BUFFERS
    "35071": {"type": "int", "value": 2048},       # MAX_ARRAY_TEXTURE_LAYERS
    "35374": {"type": "int", "value": 72},         # MAX_COMBINED_UNIFORM_BLOCKS
    "35375": {"type": "int", "value": 65536},      # MAX_UNIFORM_BLOCK_SIZE
    "35376": {"type": "int", "value": 72},         # MAX_UNIFORM_BUFFER_BINDINGS
    "35380": {"type": "int", "value": 256},        # UNIFORM_BUFFER_OFFSET_ALIGNMENT
    "36063": {"type": "int", "value": 8},          # MAX_COLOR_ATTACHMENTS
    "36183": {"type": "int", "value": 4},          # MAX_SAMPLES
}

_SHADER_PRECISION = {
    # key = "<shader GLenum>:<precision GLenum>"
    "35633:36336": [8, 8, 0],        # vertex/low float
    "35633:36337": [14, 14, 10],     # vertex/medium float
    "35633:36338": [127, 127, 23],   # vertex/high float
    "35632:36336": [8, 8, 0],        # fragment/low float
    "35632:36337": [14, 14, 10],
    "35632:36338": [127, 127, 23],
    "35633:36339": [8, 7, 0],        # vertex/low int
    "35633:36340": [15, 14, 0],
    "35633:36341": [31, 30, 0],
    "35632:36339": [8, 7, 0],
    "35632:36340": [15, 14, 0],
    "35632:36341": [31, 30, 0],
}

_WEBGL1_EXTENSIONS = [
    "ANGLE_instanced_arrays", "EXT_blend_minmax", "EXT_color_buffer_half_float",
    "EXT_float_blend", "EXT_frag_depth", "EXT_shader_texture_lod",
    "EXT_sRGB", "EXT_texture_filter_anisotropic", "OES_element_index_uint",
    "OES_fbo_render_mipmap", "OES_standard_derivatives", "OES_texture_float",
    "OES_texture_float_linear", "OES_texture_half_float",
    "OES_texture_half_float_linear", "OES_vertex_array_object",
    "WEBGL_color_buffer_float", "WEBGL_compressed_texture_s3tc",
    "WEBGL_debug_renderer_info", "WEBGL_debug_shaders",
    "WEBGL_depth_texture", "WEBGL_draw_buffers", "WEBGL_lose_context",
    "WEBGL_multi_draw",
]

_WEBGL2_EXTENSIONS = [
    "EXT_color_buffer_float", "EXT_float_blend", "EXT_texture_filter_anisotropic",
    "OES_draw_buffers_indexed", "OES_texture_float_linear",
    "OVR_multiview2", "WEBGL_compressed_texture_s3tc",
    "WEBGL_debug_renderer_info", "WEBGL_debug_shaders",
    "WEBGL_lose_context", "WEBGL_multi_draw",
]

_WEBGPU_BASE_LIMITS = {
    "maxTextureDimension1D": 8192,
    "maxTextureDimension2D": 8192,
    "maxTextureDimension3D": 2048,
    "maxTextureArrayLayers": 256,
    "maxBindGroups": 4,
    "maxBindingsPerBindGroup": 1000,
    "maxDynamicUniformBuffersPerPipelineLayout": 8,
    "maxDynamicStorageBuffersPerPipelineLayout": 4,
    "maxSampledTexturesPerShaderStage": 16,
    "maxSamplersPerShaderStage": 16,
    "maxStorageBuffersPerShaderStage": 8,
    "maxStorageTexturesPerShaderStage": 4,
    "maxUniformBuffersPerShaderStage": 12,
    "maxUniformBufferBindingSize": 65536,
    "maxStorageBufferBindingSize": 134217728,
    "minUniformBufferOffsetAlignment": 256,
    "minStorageBufferOffsetAlignment": 256,
    "maxVertexBuffers": 8,
    "maxBufferSize": 268435456,
    "maxVertexAttributes": 16,
    "maxVertexBufferArrayStride": 2048,
    "maxInterStageShaderVariables": 16,
    "maxColorAttachments": 8,
    "maxComputeWorkgroupStorageSize": 16384,
    "maxComputeInvocationsPerWorkgroup": 256,
    "maxComputeWorkgroupSizeX": 256,
    "maxComputeWorkgroupSizeY": 256,
    "maxComputeWorkgroupSizeZ": 64,
    "maxComputeWorkgroupsPerDimension": 65535,
}


def _speech_voices(os_name, locale):
    """构造系统级本地 voice 列表；没有可靠系统默认时不虚构额外 voice。"""
    if os_name == "windows":
        names = _WINDOWS_VOICE_NAMES.get(locale, ())
    elif os_name == "mac":
        names = _MAC_VOICE_NAMES.get(locale, ())
    elif os_name == "android":
        # Android TTS 的 voice name 由当前引擎决定；AOSP 默认实现使用 BCP-47。
        names = (locale,)
    else:
        # Linux 是否安装 speech-dispatcher/espeak 是宿主配置，不假装一定存在。
        return []
    return [
        {
            "name": name,
            "lang": locale,
            "voiceURI": name,
            "localService": True,
            "default": index == 0,
        }
        for index, name in enumerate(names)
    ]


def _normalized_gpu_identity(vendor, renderer):
    """把 WebGL 的 ANGLE/Mesa 字符串归一成 WebGPU adapter 可见身份。"""
    if "Apple" in vendor or renderer.startswith("Apple "):
        return "Apple", renderer
    for name in ("NVIDIA", "Intel", "AMD", "Qualcomm", "Samsung", "ARM"):
        if name.lower() in f"{vendor} {renderer}".lower():
            normalized_vendor = name
            break
    else:
        normalized_vendor = vendor

    if "ANGLE (" in renderer:
        body = renderer.split("ANGLE (", 1)[1].rsplit(")", 1)[0]
        body = re.sub(
            r"\s+(?:Direct3D\d+|D3D\d+|vs_[^, ]+|ps_[^, ]+).*$",
            "",
            body,
        )
        parts = [part.strip() for part in body.split(",") if part.strip()]
        description = next(
            (part for part in parts if any(
                token in part
                for token in (
                    "GeForce", "Radeon", "Graphics", "Arc", "UHD", "Iris",
                )
            )),
            parts[-1] if parts else renderer,
        )
    else:
        description = renderer
    return normalized_vendor, description


def _capability_bundle(os_name, engine, device, locale):
    renderer = device["gpu"][1]
    adapter_vendor, adapter_description = _normalized_gpu_identity(
        device["gpu"][0], renderer
    )
    is_mobile = os_name == "android"
    is_apple = os_name == "mac" or "Apple" in renderer
    backend = (
        "metal" if is_apple else
        "vulkan" if os_name in ("linux", "android") else
        "d3d12"
    )
    adapter_type = "integrated-gpu" if any(
        token in renderer for token in ("Intel", "UHD", "Iris", "Apple", "Mali", "Adreno", "Xclipse")
    ) else "discrete-gpu"
    webgpu_features = (
        ["depth32float-stencil8", "texture-compression-etc2",
         "texture-compression-astc", "indirect-first-instance",
         "core-features-and-limits"]
        if is_mobile else
        ["depth32float-stencil8", "texture-compression-bc",
         "timestamp-query", "indirect-first-instance",
         "float32-filterable", "core-features-and-limits"]
    )
    common_codecs = {
        'audio/webm; codecs="opus"': "probably",
        'audio/ogg; codecs="opus"': "probably",
        'video/webm; codecs="vp8"': "probably",
        'video/webm; codecs="vp9"': "probably",
        'video/webm; codecs="av01.0.05M.08"': "probably",
    }
    platform_codecs = {}
    if os_name in ("windows", "mac", "android"):
        platform_codecs = {
            'audio/mp4; codecs="mp4a.40.2"': "probably",
            'video/mp4; codecs="avc1.42E01E"': "probably",
        }
    decoding_info = {
        content_type: {
            "supported": True,
            "smooth": True,
            # Conservatively avoid claiming hardware acceleration until a
            # real-device dataset ties this exact codec to this GPU.
            "powerEfficient": False,
        }
        for content_type in (*common_codecs, *platform_codecs)
    }

    # Chromium and current Firefox intentionally expose the same fixed five
    # PDF compatibility entries. This is not a legacy NPAPI inventory.
    plugins = [
        {
            "name": "PDF Viewer",
            "filename": "internal-pdf-viewer",
            "description": "Portable Document Format",
            "mimeTypes": ["application/pdf", "text/pdf"],
        },
        {
            "name": "Chrome PDF Viewer",
            "filename": "internal-pdf-viewer",
            "description": "Portable Document Format",
            "mimeTypes": ["application/pdf", "text/pdf"],
        },
        {
            "name": "Chromium PDF Viewer",
            "filename": "internal-pdf-viewer",
            "description": "Portable Document Format",
            "mimeTypes": ["application/pdf", "text/pdf"],
        },
        {
            "name": "Microsoft Edge PDF Viewer",
            "filename": "internal-pdf-viewer",
            "description": "Portable Document Format",
            "mimeTypes": ["application/pdf", "text/pdf"],
        },
        {
            "name": "WebKit built-in PDF",
            "filename": "internal-pdf-viewer",
            "description": "Portable Document Format",
            "mimeTypes": ["application/pdf", "text/pdf"],
        },
    ]
    mime_types = [
        {
            "type": "application/pdf",
            "suffixes": "pdf",
            "description": "Portable Document Format",
        },
        {
            "type": "text/pdf",
            "suffixes": "pdf",
            "description": "Portable Document Format",
        },
    ]

    media_devices = [
        {"kind": "audioinput", "deviceId": "default", "groupId": "", "label": ""},
        {"kind": "audiooutput", "deviceId": "default", "groupId": "", "label": ""},
    ]
    if os_name != "linux":
        media_devices.insert(
            1,
            {"kind": "videoinput", "deviceId": "default", "groupId": "", "label": ""},
        )

    webgl_extensions = list(_WEBGL1_EXTENSIONS)
    webgl2_extensions = list(_WEBGL2_EXTENSIONS)
    if is_mobile:
        mobile_compression = [
            "WEBGL_compressed_texture_astc",
            "WEBGL_compressed_texture_etc",
            "WEBGL_compressed_texture_etc1",
        ]
        webgl_extensions = [
            extension for extension in webgl_extensions
            if extension != "WEBGL_compressed_texture_s3tc"
        ] + mobile_compression
        webgl2_extensions = [
            extension for extension in webgl2_extensions
            if extension != "WEBGL_compressed_texture_s3tc"
        ] + mobile_compression[:2]

    webgl_parameters = dict(
        _WEBGL_MOBILE_PARAMETERS if is_mobile else _WEBGL_DESKTOP_PARAMETERS
    )
    webgpu_limits = dict(_WEBGPU_BASE_LIMITS)
    if not is_mobile:
        webgpu_limits["maxTextureDimension1D"] = 16384
        webgpu_limits["maxTextureDimension2D"] = 16384

    return {
        "font_families": list(_FONT_FAMILIES[os_name]),
        "font_aliases": dict(_FONT_ALIASES[os_name]),
        "speech_voices": _speech_voices(os_name, locale),
        "media_codecs": {
            "canPlayType": {**common_codecs, **platform_codecs},
            "mediaSource": list((*common_codecs, *platform_codecs)),
            "decodingInfo": decoding_info,
        },
        "media_devices": media_devices,
        "plugins": [] if is_mobile else plugins,
        "mime_types": [] if is_mobile else mime_types,
        # Pixel 3 Chrome：plugins=[], pdfViewerEnabled=false。桌面仍是内置 PDF 五项。
        "pdf_viewer_enabled": not is_mobile,
        "webgl_extensions": webgl_extensions,
        "webgl2_extensions": webgl2_extensions,
        "webgl_parameters": webgl_parameters,
        "webgl2_parameters": dict(_WEBGL2_PARAMETERS),
        "webgl_shader_precision": dict(_SHADER_PRECISION),
        "webgl2_shader_precision": dict(_SHADER_PRECISION),
        "webgpu": {
            "adapter": {
                "vendor": adapter_vendor,
                "architecture": "",
                "device": "",
                "description": adapter_description,
                "backend": backend,
                "type": adapter_type,
                "isFallbackAdapter": False,
                "subgroupMinSize": 4 if is_mobile else 32,
                "subgroupMaxSize": 128 if is_mobile else 32,
            },
            # 浏览器端只保留底层真实支持的交集；不会因画像虚构出不可用 feature。
            "features": webgpu_features,
            # limits 只允许向更保守方向收敛，requestDevice 与暴露值保持一致。
            "limits": webgpu_limits,
            "preferredCanvasFormat": (
                "rgba8unorm" if os_name in ("linux", "android")
                else "bgra8unorm"
            ),
        },
        "css_media": {
            "colorGamut": "p3" if is_apple else "srgb",
            "dynamicRange": "standard",
            "forcedColors": "none",
            "prefersContrast": "no-preference",
            "prefersReducedMotion": "no-preference",
        },
        "product_capabilities": {
            "engine": engine,
            "platform": os_name,
            "linuxDistro": "Ubuntu" if os_name == "linux" else "",
            "linuxDistroVersion": "24.04" if os_name == "linux" else "",
            "desktopEnvironment": "GNOME" if os_name == "linux" else "",
            "uaCH": engine == "chrome",
            "pdfViewer": not is_mobile,
            "widevine": engine == "chrome",
            "geckoView": engine == "firefox" and os_name == "android",
        },
    }

# ── 移动端 / macOS 整机画像 ──
#
# 强相关字段必须作为一个整体抽样，不能把机型、GPU、逻辑分辨率、DPR、核心数拆开随机。
# Chrome Android 的 UA 已降熵为 Android 10; K，真实 model/version 只经 UA-CH 下发。

_ANDROID_DEVICES = [
    {
        "model": "Pixel 6", "platform_versions": ("12.0.0", "13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 915), "dpr": 2.625,
        "gpu": ("ARM", "Mali-G78 MP20"), "cores": 8, "memory": 8, "weight": 7,
    },
    {
        "model": "Pixel 6 Pro", "platform_versions": ("12.0.0", "13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 892), "dpr": 3.5,
        "gpu": ("ARM", "Mali-G78 MP20"), "cores": 8, "memory": 8, "weight": 4,
    },
    {
        "model": "Pixel 6a", "platform_versions": ("12.0.0", "13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 915), "dpr": 2.625,
        "gpu": ("ARM", "Mali-G78 MP20"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "Pixel 7", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 915), "dpr": 2.625,
        "gpu": ("ARM", "Mali-G710 MP7"), "cores": 8, "memory": 8, "weight": 8,
    },
    {
        "model": "Pixel 7 Pro", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 892), "dpr": 3.5,
        "gpu": ("ARM", "Mali-G710 MP7"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "Pixel 7a", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 915), "dpr": 2.625,
        "gpu": ("ARM", "Mali-G710 MP7"), "cores": 8, "memory": 8, "weight": 6,
    },
    {
        "model": "Pixel 8", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (393, 873), "dpr": 2.75,
        "gpu": ("ARM", "Immortalis-G715s MC10"), "cores": 8, "memory": 8, "weight": 8,
    },
    {
        "model": "Pixel 8 Pro", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (384, 855), "dpr": 3.5,
        "gpu": ("ARM", "Immortalis-G715s MC10"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "Pixel 8a", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (412, 915), "dpr": 2.625,
        "gpu": ("ARM", "Immortalis-G715s MC10"), "cores": 8, "memory": 8, "weight": 6,
    },
    {
        "model": "SM-G991B", "platform_versions": ("12.0.0", "13.0.0", "14.0.0", "15.0.0"),
        "screen": (360, 800), "dpr": 3.0,
        "gpu": ("ARM", "Mali-G78 MP14"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "SM-G998B", "platform_versions": ("12.0.0", "13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 915), "dpr": 3.5,
        "gpu": ("ARM", "Mali-G78 MP14"), "cores": 8, "memory": 8, "weight": 3,
    },
    {
        "model": "SM-S901B", "platform_versions": ("12.0.0", "13.0.0", "14.0.0", "15.0.0"),
        "screen": (360, 780), "dpr": 3.0,
        "gpu": ("Samsung", "Xclipse 920"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "SM-S908B", "platform_versions": ("12.0.0", "13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 883), "dpr": 3.5,
        "gpu": ("Samsung", "Xclipse 920"), "cores": 8, "memory": 8, "weight": 3,
    },
    {
        "model": "SM-S911B", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (360, 780), "dpr": 3.0,
        "gpu": ("Qualcomm", "Adreno (TM) 740"), "cores": 8, "memory": 8, "weight": 8,
    },
    {
        "model": "SM-S918B", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 883), "dpr": 3.5,
        "gpu": ("Qualcomm", "Adreno (TM) 740"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "SM-S921U", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (360, 780), "dpr": 3.0,
        "gpu": ("Qualcomm", "Adreno (TM) 750"), "cores": 8, "memory": 8, "weight": 7,
    },
    {
        "model": "SM-S928B", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (412, 883), "dpr": 3.5,
        "gpu": ("Qualcomm", "Adreno (TM) 750"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "SM-A546B", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (360, 780), "dpr": 3.0,
        "gpu": ("ARM", "Mali-G68 MP5"), "cores": 8, "memory": 8, "weight": 8,
    },
    {
        "model": "SM-A556B", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (360, 780), "dpr": 3.0,
        "gpu": ("Samsung", "Xclipse 530"), "cores": 8, "memory": 8, "weight": 7,
    },
    {
        "model": "SM-A346B", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (360, 780), "dpr": 3.0,
        "gpu": ("ARM", "Mali-G68 MC4"), "cores": 8, "memory": 8, "weight": 6,
    },
    {
        "model": "LE2113", "platform_versions": ("12.0.0", "13.0.0", "14.0.0"),
        "screen": (360, 800), "dpr": 3.0,
        "gpu": ("Qualcomm", "Adreno (TM) 660"), "cores": 8, "memory": 8, "weight": 4,
    },
    {
        "model": "NE2213", "platform_versions": ("12.0.0", "13.0.0", "14.0.0"),
        "screen": (412, 919), "dpr": 3.5,
        "gpu": ("Qualcomm", "Adreno (TM) 730"), "cores": 8, "memory": 8, "weight": 4,
    },
    {
        "model": "CPH2449", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (412, 919), "dpr": 3.5,
        "gpu": ("Qualcomm", "Adreno (TM) 740"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "CPH2581", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (412, 905), "dpr": 3.5,
        "gpu": ("Qualcomm", "Adreno (TM) 750"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "2201123G", "platform_versions": ("12.0.0", "13.0.0", "14.0.0"),
        "screen": (360, 800), "dpr": 3.0,
        "gpu": ("Qualcomm", "Adreno (TM) 730"), "cores": 8, "memory": 8, "weight": 4,
    },
    {
        "model": "2211133G", "platform_versions": ("13.0.0", "14.0.0", "15.0.0"),
        "screen": (360, 800), "dpr": 3.0,
        "gpu": ("Qualcomm", "Adreno (TM) 740"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "23127PN0CG", "platform_versions": ("14.0.0", "15.0.0"),
        "screen": (400, 890), "dpr": 3.0,
        "gpu": ("Qualcomm", "Adreno (TM) 750"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "22101316G", "platform_versions": ("12.0.0", "13.0.0", "14.0.0"),
        "screen": (360, 800), "dpr": 3.0,
        "gpu": ("ARM", "Mali-G68 MC4"), "cores": 8, "memory": 8, "weight": 5,
    },
    {
        "model": "23013PC75G", "platform_versions": ("13.0.0", "14.0.0"),
        "screen": (360, 800), "dpr": 3.0,
        "gpu": ("Qualcomm", "Adreno (TM) 725"), "cores": 8, "memory": 8, "weight": 4,
    },
]

_MAC_DEVICES = [
    {
        "name": "MacBook Air M1",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1440, 900, 2.0, 9), (1920, 1080, 1.0, 1)),
        "variants": (("Apple M1", 8, 10),),
        "weight": 18,
    },
    {
        "name": "MacBook Air M2",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1470, 956, 2.0, 9), (1920, 1080, 1.0, 1)),
        "variants": (("Apple M2", 8, 10),),
        "weight": 20,
    },
    {
        "name": "MacBook Pro M1 Pro",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1512, 982, 2.0, 7), (1728, 1117, 2.0, 3)),
        "variants": (("Apple M1 Pro", 8, 3), ("Apple M1 Pro", 10, 7)),
        "weight": 12,
    },
    {
        "name": "MacBook Pro M2 Pro",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1512, 982, 2.0, 7), (1728, 1117, 2.0, 3)),
        "variants": (("Apple M2 Pro", 10, 4), ("Apple M2 Pro", 12, 6)),
        "weight": 15,
    },
    {
        "name": "MacBook Air M3",
        "os_versions": (("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1470, 956, 2.0, 9), (1920, 1080, 1.0, 1)),
        "variants": (("Apple M3", 8, 10),),
        "weight": 13,
    },
    {
        "name": "MacBook Pro M3 Pro",
        "os_versions": (("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1512, 982, 2.0, 7), (1728, 1117, 2.0, 3)),
        "variants": (("Apple M3 Pro", 11, 4), ("Apple M3 Pro", 12, 6)),
        "weight": 10,
    },
    {
        "name": "Mac mini M1/M2",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": (
            (1920, 1080, 1.0, 4), (2560, 1440, 1.0, 3),
            (1920, 1080, 2.0, 2), (2560, 1440, 2.0, 1),
        ),
        "variants": (("Apple M1", 8, 4), ("Apple M2", 8, 6)),
        "weight": 8,
    },
    {
        "name": "Mac mini M2 Pro",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": (
            (1920, 1080, 1.0, 3), (2560, 1440, 1.0, 3),
            (1920, 1080, 2.0, 2), (2560, 1440, 2.0, 2),
        ),
        "variants": (("Apple M2 Pro", 10, 4), ("Apple M2 Pro", 12, 6)),
        "weight": 4,
    },
    {
        "name": "MacBook Pro M1 Max",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1512, 982, 2.0, 4), (1728, 1117, 2.0, 6)),
        "variants": (("Apple M1 Max", 10, 10),), "weight": 4,
    },
    {
        "name": "Mac Studio M1",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1920, 1080, 1.0, 3), (2560, 1440, 1.0, 3), (2560, 1440, 2.0, 4)),
        "variants": (("Apple M1 Max", 10, 7), ("Apple M1 Ultra", 20, 3)),
        "weight": 3,
    },
    {
        "name": "MacBook Pro M2 Max",
        "os_versions": (("13.0.0", "13.0"), ("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1512, 982, 2.0, 4), (1728, 1117, 2.0, 6)),
        "variants": (("Apple M2 Max", 12, 10),), "weight": 4,
    },
    {
        "name": "Mac Studio M2",
        "os_versions": (("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1920, 1080, 1.0, 3), (2560, 1440, 1.0, 3), (2560, 1440, 2.0, 4)),
        "variants": (("Apple M2 Max", 12, 7), ("Apple M2 Ultra", 24, 3)),
        "weight": 3,
    },
    {
        "name": "MacBook Pro M3 Max",
        "os_versions": (("14.6.1", "14.6"), ("15.4.1", "15.4")),
        "screens": ((1512, 982, 2.0, 4), (1728, 1117, 2.0, 6)),
        "variants": (("Apple M3 Max", 14, 4), ("Apple M3 Max", 16, 6)),
        "weight": 4,
    },
    {
        "name": "Mac M4 family",
        "os_versions": (("15.4.1", "15.4"),),
        "screens": (
            (1470, 956, 2.0, 2), (1512, 982, 2.0, 2), (1728, 1117, 2.0, 2),
            (1920, 1080, 1.0, 2), (2560, 1440, 2.0, 2),
        ),
        "variants": (
            ("Apple M4", 10, 5), ("Apple M4 Pro", 12, 2),
            ("Apple M4 Pro", 14, 2), ("Apple M4 Max", 16, 1),
        ),
        "weight": 5,
    },
]

# Windows/Linux 不冒充具体 SKU，但按常见设备族整组抽样。组内只保留合理的
# GPU、逻辑核心数、内存档位、CSS 屏幕尺寸和 DPR，避免原来各字段独立抽样。
_WINDOWS_FAMILY_SHAPES = {
    "legacy_laptop": {
        "cores": ((4, 4), (8, 6)), "memory": ((4, 3), (8, 7)),
        "screens": ((1366, 768, 1.0, 4), (1536, 864, 1.25, 4), (1920, 1080, 1.0, 2)),
    },
    "modern_laptop": {
        "cores": ((8, 3), (12, 4), (16, 3)), "memory": ((8, 10),),
        "screens": ((1536, 864, 1.25, 3), (1920, 1080, 1.0, 4), (1920, 1200, 1.25, 3)),
    },
    "legacy_desktop": {
        "cores": ((4, 2), (8, 4), (12, 3), (16, 1)), "memory": ((4, 2), (8, 8)),
        "screens": ((1920, 1080, 1.0, 8), (2560, 1440, 1.0, 2)),
    },
    "mainstream": {
        "cores": ((8, 2), (12, 3), (16, 3), (24, 2)), "memory": ((8, 10),),
        "screens": ((1920, 1080, 1.0, 5), (2560, 1440, 1.0, 5)),
    },
    "high_end": {
        "cores": ((16, 2), (20, 2), (24, 4), (32, 2)), "memory": ((8, 10),),
        "screens": ((2560, 1440, 1.0, 5), (2560, 1440, 1.25, 2), (3840, 2160, 1.5, 3)),
    },
}

_WINDOWS_GPU_CATALOG = [
    ("Intel", "Intel(R) HD Graphics 4600", "legacy_desktop", 3),
    ("Intel", "Intel(R) HD Graphics 520", "legacy_laptop", 3),
    ("Intel", "Intel(R) UHD Graphics 620", "legacy_laptop", 8),
    ("Intel", "Intel(R) UHD Graphics 630", "legacy_desktop", 7),
    ("Intel", "Intel(R) UHD Graphics 770", "mainstream", 6),
    ("Intel", "Intel(R) Iris(R) Xe Graphics", "modern_laptop", 10),
    ("Intel", "Intel(R) Arc(TM) Graphics", "modern_laptop", 4),
    ("NVIDIA", "NVIDIA GeForce GTX 1050 Ti", "legacy_desktop", 3),
    ("NVIDIA", "NVIDIA GeForce GTX 1060 6GB", "legacy_desktop", 4),
    ("NVIDIA", "NVIDIA GeForce GTX 1650", "legacy_desktop", 5),
    ("NVIDIA", "NVIDIA GeForce GTX 1660 SUPER", "legacy_desktop", 5),
    ("NVIDIA", "NVIDIA GeForce RTX 2060", "mainstream", 5),
    ("NVIDIA", "NVIDIA GeForce RTX 3050 Laptop GPU", "modern_laptop", 4),
    ("NVIDIA", "NVIDIA GeForce RTX 3060 Laptop GPU", "modern_laptop", 5),
    ("NVIDIA", "NVIDIA GeForce RTX 3060", "mainstream", 8),
    ("NVIDIA", "NVIDIA GeForce RTX 3070", "mainstream", 5),
    ("NVIDIA", "NVIDIA GeForce RTX 3080", "high_end", 3),
    ("NVIDIA", "NVIDIA GeForce RTX 4050 Laptop GPU", "modern_laptop", 4),
    ("NVIDIA", "NVIDIA GeForce RTX 4060 Laptop GPU", "modern_laptop", 6),
    ("NVIDIA", "NVIDIA GeForce RTX 4060", "mainstream", 8),
    ("NVIDIA", "NVIDIA GeForce RTX 4070 Laptop GPU", "modern_laptop", 4),
    ("NVIDIA", "NVIDIA GeForce RTX 4070", "high_end", 5),
    ("NVIDIA", "NVIDIA GeForce RTX 4080", "high_end", 3),
    ("NVIDIA", "NVIDIA GeForce RTX 4090", "high_end", 2),
    ("AMD", "AMD Radeon RX 580 Series", "legacy_desktop", 4),
    ("AMD", "AMD Radeon(TM) Vega 8 Graphics", "legacy_laptop", 4),
    ("AMD", "AMD Radeon(TM) Graphics", "modern_laptop", 7),
    ("AMD", "AMD Radeon RX 6600 XT", "mainstream", 5),
    ("AMD", "AMD Radeon RX 6700 XT", "mainstream", 4),
    ("AMD", "AMD Radeon RX 7600", "mainstream", 3),
    ("AMD", "AMD Radeon RX 7800 XT", "high_end", 3),
    ("AMD", "AMD Radeon RX 7900 XTX", "high_end", 2),
]

_WINDOWS_DEVICE_FAMILIES = [
    dict(
        _WINDOWS_FAMILY_SHAPES[shape],
        gpu=(
            f"Google Inc. ({vendor})",
            f"ANGLE ({vendor}, {renderer} Direct3D11 vs_5_0 ps_5_0, D3D11)",
        ),
        weight=weight,
    )
    for vendor, renderer, shape, weight in _WINDOWS_GPU_CATALOG
]

_LINUX_FAMILY_SHAPES = {
    "legacy": {
        "cores": ((4, 3), (8, 5), (12, 2)), "memory": ((4, 2), (8, 8)),
        "screens": ((1366, 768, 1.0, 2), (1920, 1080, 1.0, 8)),
    },
    "mainstream": {
        "cores": ((8, 3), (12, 3), (16, 3), (24, 1)), "memory": ((8, 10),),
        "screens": ((1920, 1080, 1.0, 6), (2560, 1440, 1.0, 4)),
    },
    "high_end": {
        "cores": ((12, 2), (16, 3), (24, 3), (32, 2)), "memory": ((8, 10),),
        "screens": ((2560, 1440, 1.0, 7), (3840, 2160, 1.0, 3)),
    },
}

_LINUX_GPU_CATALOG = [
    ("Mesa", "Mesa Intel(R) HD Graphics 520 (SKL GT2)", "legacy", 4),
    ("Mesa", "Mesa Intel(R) UHD Graphics 630 (CFL GT2)", "legacy", 9),
    ("Mesa", "Mesa Intel(R) Graphics (ADL GT2)", "mainstream", 8),
    ("Mesa", "Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2)", "mainstream", 7),
    ("NVIDIA Corporation", "NVIDIA GeForce GTX 1060 6GB/PCIe/SSE2", "legacy", 4),
    ("NVIDIA Corporation", "NVIDIA GeForce GTX 1080/PCIe/SSE2", "legacy", 4),
    ("NVIDIA Corporation", "NVIDIA GeForce GTX 1650/PCIe/SSE2", "legacy", 5),
    ("NVIDIA Corporation", "NVIDIA GeForce GTX 1660 SUPER/PCIe/SSE2", "legacy", 5),
    ("NVIDIA Corporation", "NVIDIA GeForce RTX 2060/PCIe/SSE2", "mainstream", 5),
    ("NVIDIA Corporation", "NVIDIA GeForce RTX 3060/PCIe/SSE2", "mainstream", 8),
    ("NVIDIA Corporation", "NVIDIA GeForce RTX 3070/PCIe/SSE2", "mainstream", 5),
    ("NVIDIA Corporation", "NVIDIA GeForce RTX 4060/PCIe/SSE2", "mainstream", 7),
    ("NVIDIA Corporation", "NVIDIA GeForce RTX 4070/PCIe/SSE2", "high_end", 4),
    ("AMD", "AMD Radeon RX 580 Series (polaris10, LLVM 15.0.7, DRM 3.49)", "legacy", 4),
    ("AMD", "AMD Radeon RX 6600 XT (navi23, LLVM 15.0.7, DRM 3.49)", "mainstream", 5),
    ("AMD", "AMD Radeon RX 6700 XT (navi22, LLVM 15.0.7, DRM 3.49)", "mainstream", 5),
    ("AMD", "AMD Radeon RX 7600 (gfx1102, LLVM 17.0.6, DRM 3.57)", "mainstream", 3),
    ("AMD", "AMD Radeon RX 7800 XT (gfx1101, LLVM 17.0.6, DRM 3.57)", "high_end", 3),
]

_LINUX_DEVICE_FAMILIES = [
    dict(
        _LINUX_FAMILY_SHAPES[shape],
        gpu=(vendor, renderer),
        weight=weight,
    )
    for vendor, renderer, shape, weight in _LINUX_GPU_CATALOG
]

# ── Windows platform_version 池 ──

_WIN_PLATFORM_VERSIONS = [
    "10.0.0",  # Windows 10
    "15.0.0",  # Windows 11
]
_WIN_PLATFORM_WEIGHTS = [40, 60]

# ── macOS 版本池（UA 里的 10_15_7 或 14_x 格式）──

_MACOS_VERSIONS = [
    ("10_15_7", "13.0.0"),
    ("14_5", "14.5.0"),
    ("14_6_1", "14.6.1"),
    ("15_0", "15.0.0"),
    ("15_1", "15.1.0"),
    ("15_4_1", "15.4.1"),
]
_MACOS_WEIGHTS = [10, 15, 15, 20, 20, 20]

# ── Not A Brand 池（Chrome GREASE）──

_NOT_A_BRANDS = [
    "Not_A Brand",
    "Not/A)Brand",
    "Not)A;Brand",
    "Not.A/Brand",
]


def _weighted_choice(items_with_weight):
    items = [x[:-1] if len(x) > 2 else (x[0],) for x in items_with_weight]
    weights = [x[-1] for x in items_with_weight]
    chosen = random.choices(items, weights=weights, k=1)[0]
    return chosen if len(chosen) > 1 else chosen[0]


class Profile:
    """从 engine + region 生成完整自洽指纹。"""

    def __init__(self, engine, region, version=None, os=None):
        """
        engine:  "chrome" / "edge" / "firefox" / "random"，不传默认 chrome
        region:  国家代码（"us", "jp", "de" 等），或 "random"
        version: 指定大版本号；不传时加权随机大版本，再从真实完整版本中采样
        os:      "windows" / "mac" / "linux" / "android" / "random"；不传默认 windows
        """
        engine = str(engine).strip().lower() if engine is not None else ""
        if not engine:
            engine = "chrome"
        elif engine == "random":
            engine = _pick_random_profile_value(("chrome", "edge", "firefox"))
        if engine not in ("chrome", "edge", "firefox"):
            raise ValueError(
                f"engine must be chrome/edge/firefox/random, not {engine!r}"
            )
        region = region.lower()
        if region == "random":
            region = _pick_random_profile_value(_REGIONS)
        if region not in _REGIONS:
            raise ValueError(f"unsupported region: {region!r}, choices: {list(_REGIONS.keys())}")

        self._browser = engine
        self.engine = "chrome" if engine in ("chrome", "edge") else "firefox"
        self.region = region
        os = str(os).strip().lower() if os is not None else ""
        self.os = os or "windows"
        if self.os == "random":
            self.os = _pick_random_profile_value(
                ("windows", "mac", "linux", "android")
            )
        if self.os not in ("windows", "mac", "linux", "android"):
            raise ValueError(
                f"os must be windows/mac/linux/android/random, not {self.os!r}"
            )

        reg = _REGIONS[region]
        self._tz = reg["tz"]
        self._locale = reg["locale"]
        self._langs = reg["langs"]
        # 每个 persona 一个确定性读回种子：魔改浏览器据此对 canvas/WebGL readback 加
        # 稳定噪声，让同一画像的读回结果自洽且可复现（防画布指纹每次抖动被判异常）。
        # Chromium/Firefox 的跨协议实现按有符号 int32 消费该字段。
        # 保持为正数，避免 bit 31 置位后在 C++ 侧溢出或被拒绝。
        self._readback_seed = random.randint(1, 0x7FFFFFFF)

        if self.engine == "chrome":
            self._build_chrome(version)
        else:
            self._build_firefox(version)

    def _pick_device(self):
        """一次选出所有强相关硬件字段，避免跨设备随机拼接。"""
        if self.os == "android":
            base = random.choices(
                _ANDROID_DEVICES,
                weights=[d["weight"] for d in _ANDROID_DEVICES],
                k=1,
            )[0]
            return self._materialize_android_device(base)
        if self.os == "mac":
            base = random.choices(
                _MAC_DEVICES,
                weights=[d["weight"] for d in _MAC_DEVICES],
                k=1,
            )[0]
            return self._materialize_mac_device(base)

        families = (
            _LINUX_DEVICE_FAMILIES if self.os == "linux"
            else _WINDOWS_DEVICE_FAMILIES
        )
        family = random.choices(
            families, weights=[d["weight"] for d in families], k=1
        )[0]
        screen_w, screen_h, dpr = _weighted_choice(family["screens"])
        return {
            "screen": (screen_w, screen_h),
            "dpr": dpr,
            "gpu": family["gpu"],
            "cores": _weighted_choice(family["cores"]),
            "memory": _weighted_choice(family["memory"]),
            "weight": 1,
        }

    @staticmethod
    def _materialize_android_device(base, platform_version=None):
        device = dict(base)
        versions = device.pop("platform_versions")
        device["platform_version"] = platform_version or random.choice(versions)
        return device

    @staticmethod
    def _materialize_mac_device(base, os_versions=None):
        versions = os_versions or base["os_versions"]
        platform_version, firefox_os = random.choice(versions)
        screen_w, screen_h, dpr = _weighted_choice(base["screens"])
        gpu_name, cores = _weighted_choice(base["variants"])
        return {
            "name": base["name"],
            "platform_version": platform_version,
            "firefox_os": firefox_os,
            "screen": (screen_w, screen_h),
            "dpr": dpr,
            "gpu": ("Apple", gpu_name),
            "cores": cores,
            "memory": 8,
            "weight": base["weight"],
        }

    def _pick_device_for_ua(self, ua):
        """from_ua 优先复用 UA 已暴露的机型/系统，避免再抽到冲突设备。"""
        if self.os == "android":
            version_match = re.search(r"Android\s+([\d.]+)", ua)
            android_version = version_match.group(1) if version_match else None
            model = None
            if self.engine == "chrome":
                model_match = re.search(
                    r"Linux;\s*Android\s+[\d.]+;\s*([^)]+)", ua
                )
                if model_match:
                    model = model_match.group(1).split(";", 1)[0].strip()
                    model = re.sub(r"\s+Build/.*$", "", model).strip()
                    if model in ("K", "Mobile", "Tablet", "wv"):
                        model = None

            # Chromium 的 `Android 10; K` 是冻结后的低熵值，不能把它当成
            # 真实 Android 10。Firefox 没有 UA-CH，其 Android 版本则是强约束。
            reduced_chromium = (
                self.engine == "chrome"
                and android_version == "10"
                and model is None
                and re.search(r"Android\s+10;\s*K\)", ua)
            )
            forced_version = None
            if android_version and not reduced_chromium:
                parts = android_version.split(".")[:3]
                forced_version = ".".join(parts + ["0"] * (3 - len(parts)))

            candidates = _ANDROID_DEVICES
            if model:
                model_matches = [
                    d for d in candidates if d["model"].lower() == model.lower()
                ]
                if model_matches:
                    candidates = model_matches
            elif forced_version:
                major = forced_version.split(".", 1)[0]
                version_matches = [
                    d for d in candidates
                    if any(v.split(".", 1)[0] == major
                           for v in d["platform_versions"])
                ]
                if version_matches:
                    candidates = version_matches

            base = random.choices(
                candidates,
                weights=[d["weight"] for d in candidates],
                k=1,
            )[0]
            device = self._materialize_android_device(base, forced_version)
            if model:
                device["model"] = model
            return device
        if self.os == "mac" and self.engine == "firefox":
            candidates = []
            for base in _MAC_DEVICES:
                versions = [
                    pair for pair in base["os_versions"]
                    if pair[1].replace(".", "_") in ua
                ]
                if versions:
                    candidates.append((base, versions))
            if candidates:
                base, versions = random.choices(
                    candidates,
                    weights=[item[0]["weight"] for item in candidates],
                    k=1,
                )[0]
                return self._materialize_mac_device(base, versions)
            return self._pick_device()
        return self._pick_device()

    def _derive_avail(self, w, h):
        """由整屏推导可用区。避免与整屏相同——真机有任务栏/菜单栏/dock，两者相等本身是特征。"""
        if self.os == "android":
            return w, h, 0, 0                       # 移动端可用区≈整屏
        if self.os == "mac":
            return w, h - 25, 0, 25                 # 顶部菜单栏 25px（dock 自动隐藏）
        return w, h - random.choice([40, 48, 63]), 0, 0   # win/linux 底部任务栏

    def _derive_window(self, avail_w, avail_h, dpr=1):
        """使用最大化窗口，保证 outer/viewport/screen 三组值可被实际同步。"""
        if self.os == "android":
            # Pixel 3 真机：inner 392×632 vs screen 393×786，outer≈screen。
            chrome_h = max(56, int(round(56 * float(dpr or 1))))
            return {
                "outer_width": avail_w,
                "outer_height": avail_h,
                "viewport_width": avail_w,
                "viewport_height": max(480, avail_h - chrome_h),
            }
        browser_chrome = 86 if self.os == "windows" else 88
        return {
            "outer_width": avail_w,
            "outer_height": avail_h,
            "viewport_width": avail_w,
            "viewport_height": max(480, avail_h - browser_chrome),
        }

    def _pick_color_depth(self):
        return _weighted_choice([(24, 92), (30, 8)])       # 真机绝大多数 24，少数 HDR 30

    def _pick_device_memory(self):
        return _weighted_choice([(8, 72), (4, 22), (2, 6)])  # Chrome 量化且封顶 8

    # ── Chrome ──

    def _build_chrome(self, version):
        is_edge = self._browser == "edge"
        edge_pool = (
            _EDGE_ANDROID_VERSIONS if self.os == "android"
            else _EDGE_DESKTOP_VERSIONS
        )
        major_pool = edge_pool if is_edge else _CHROME_VERSIONS
        requested = str(version) if version is not None else None
        ver = requested.split(".", 1)[0] if requested else _pick_version_weighted(
            major_pool.keys()
        )
        chrome_info = _CHROME_VERSIONS.get(ver)
        if not chrome_info:
            raise ValueError(f"unsupported explicit Chrome version: {version!r}")
        chrome_build, chrome_patches = chrome_info

        if requested and requested.count(".") >= 3 and not is_edge:
            full_ver = requested
        else:
            full_ver = f"{ver}.0.{chrome_build}.{random.choice(chrome_patches)}"

        edge_ver = None
        if is_edge:
            edge_info = edge_pool.get(ver)
            if not edge_info:
                raise ValueError(f"unsupported explicit Edge version: {version!r}")
            edge_build, edge_patches = edge_info
            valid_edge_versions = {
                f"{ver}.0.{edge_build}.{patch}" for patch in edge_patches
            }
            if requested and requested.count(".") >= 3:
                if requested not in valid_edge_versions:
                    raise ValueError(
                        f"unsupported explicit Edge version: {version!r}"
                    )
                edge_ver = requested
            else:
                edge_ver = f"{ver}.0.{edge_build}.{random.choice(edge_patches)}"

        self.version = ver
        self.full_version = edge_ver or full_ver

        ua_ver = f"{ver}.0.0.0"  # 真实 Chrome UA 用精简版(MAJOR.0.0.0)，完整版仅在 userAgentData

        # 真实 Chrome GREASE：品牌/版本/顺序按大版本确定性生成（对齐 Chromium user_agent_utils）
        _mi = int(ver) if str(ver).isdigit() else 151
        _gchars = [" ", "(", ":", "-", ".", "/", ")", ";", "=", "?", "_"]
        _gvers = ["8", "99", "24"]
        grease_brand = f"Not{_gchars[_mi % 11]}A{_gchars[(_mi + 1) % 11]}Brand"
        grease_ver = _gvers[_mi % 3]
        _orders = {0: (0, 1, 2), 1: (0, 2, 1), 2: (1, 0, 2),
                   3: (1, 2, 0), 4: (2, 0, 1), 5: (2, 1, 0)}

        if is_edge:
            base = [
                {"brand": grease_brand, "version": f"{grease_ver}.0.0.0"},
                {"brand": "Chromium", "version": full_ver},
                {"brand": "Microsoft Edge", "version": edge_ver},
            ]
        else:
            base = [
                {"brand": grease_brand, "version": f"{grease_ver}.0.0.0"},
                {"brand": "Chromium", "version": full_ver},
                {"brand": "Google Chrome", "version": full_ver},
            ]
        brands = [base[i] for i in _orders[_mi % 6]]

        device = self._pick_device()

        # UA string
        if is_edge and self.os == "android":
            edg_suffix = f" EdgA/{edge_ver}"
        elif is_edge:
            edg_suffix = f" Edg/{edge_ver}"
        else:
            edg_suffix = ""
        if self.os == "android":
            # Chrome UA Reduction：Android 版本/型号在低熵 UA 中固定，真实值走 UA-CH。
            ua = (f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                  f"(KHTML, like Gecko) Chrome/{ua_ver} Mobile Safari/537.36{edg_suffix}")
            pv = device["platform_version"]
        elif self.os == "windows":
            ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  f"(KHTML, like Gecko) Chrome/{ua_ver} Safari/537.36{edg_suffix}")
            pv = random.choices(_WIN_PLATFORM_VERSIONS, _WIN_PLATFORM_WEIGHTS, k=1)[0]
        elif self.os == "mac":
            # Chrome 的 macOS 低熵 UA 固定为 10_15_7；真实系统版本经 UA-CH 下发。
            pv = device["platform_version"]
            ua = (f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  f"(KHTML, like Gecko) Chrome/{ua_ver} Safari/537.36{edg_suffix}")
        else:
            ua = (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  f"(KHTML, like Gecko) Chrome/{ua_ver} Safari/537.36{edg_suffix}")
            pv = "6.8.0"

        screen_w, screen_h = device["screen"]
        avail_w, avail_h, avail_l, avail_t = self._derive_avail(screen_w, screen_h)
        window = self._derive_window(avail_w, avail_h, device["dpr"])
        gpu_vendor, gpu_renderer = device["gpu"]
        cores = device["cores"]
        capabilities = _capability_bundle(
            self.os, self.engine, device, self._locale
        )

        self.fingerprint = Fingerprint(
            user_agent=ua,
            ua_full_brands=brands,
            platform_version=pv,
            architecture=(
                "" if self.os == "android" else
                ("arm" if self.os == "mac" else "x86")
            ),
            model=device["model"] if self.os == "android" else "",
            mobile=self.os == "android",
            bitness="" if self.os == "android" else "64",
            wow64=False,
            hardware_concurrency=cores,
            accept_languages=_accept_language_q(self._langs),
            locale=self._locale,
            timezone=self._tz,
            screen_width=screen_w,
            screen_height=screen_h,
            avail_width=avail_w,
            avail_height=avail_h,
            avail_left=avail_l,
            avail_top=avail_t,
            color_depth=self._pick_color_depth(),
            device_memory=device.get("memory", 8),
            dpr=device["dpr"],
            max_touch_points=5 if self.os == "android" else 0,
            webgl_vendor=gpu_vendor,
            webgl_renderer=gpu_renderer,
            readback_seed=self._readback_seed,
            **window,
            **capabilities,
        )
        self.user_agent = ua

    # ── Firefox ──

    def _build_firefox(self, version):
        requested = str(version) if version is not None else None
        ver = requested.split(".", 1)[0] if requested else _pick_version_weighted(
            _FIREFOX_VERSIONS.keys()
        )
        if requested and requested.count(".") >= 1:
            full_ver = requested
        else:
            vers = _FIREFOX_VERSIONS.get(ver)
            if not vers:
                raise ValueError(f"unsupported explicit Firefox version: {version!r}")
            full_ver = random.choice(vers)
        self.version = ver
        self.full_version = full_ver
        public_ver = f"{ver}.0"
        device = self._pick_device()

        # UA string
        if self.os == "android":
            android_ver = device["platform_version"].split(".", 1)[0]
            ua = (f"Mozilla/5.0 (Android {android_ver}; Mobile; rv:{public_ver}) "
                  f"Gecko/{public_ver} Firefox/{public_ver}")
        elif self.os == "windows":
            ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{public_ver}) "
                  f"Gecko/20100101 Firefox/{public_ver}")
        elif self.os == "mac":
            mac_ver = device["firefox_os"].replace(".", "_")
            ua = (f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}; rv:{public_ver}) "
                  f"Gecko/20100101 Firefox/{public_ver}")
        else:
            ua = (f"Mozilla/5.0 (X11; Linux x86_64; rv:{public_ver}) "
                  f"Gecko/20100101 Firefox/{public_ver}")

        screen_w, screen_h = device["screen"]
        avail_w, avail_h, avail_l, avail_t = self._derive_avail(screen_w, screen_h)
        window = self._derive_window(avail_w, avail_h, device["dpr"])
        gpu_vendor, gpu_renderer = device["gpu"]
        cores = device["cores"]
        capabilities = _capability_bundle(
            self.os, self.engine, device, self._locale
        )

        self.fingerprint = Fingerprint(
            user_agent=ua,
            platform="Linux armv81" if self.os == "android" else None,
            oscpu="Linux armv81" if self.os == "android" else None,
            app_version=ua.removeprefix("Mozilla/"),
            hardware_concurrency=cores,
            accept_languages=_accept_language_q(self._langs),
            locale=self._locale,
            timezone=self._tz,
            screen_width=screen_w,
            screen_height=screen_h,
            avail_width=avail_w,
            avail_height=avail_h,
            avail_left=avail_l,
            avail_top=avail_t,
            color_depth=self._pick_color_depth(),
            dpr=device["dpr"],
            max_touch_points=5 if self.os == "android" else 0,
            webgl_vendor=gpu_vendor,
            webgl_renderer=gpu_renderer,
            readback_seed=self._readback_seed,
            **window,
            **capabilities,
        )
        self.user_agent = ua

    @classmethod
    def from_ua(cls, ua, region):
        """从已有 UA 字符串 + region 派生完整指纹。

        自动识别 engine/version/os，保留原始 UA，其余维度（screen/GPU/cores）随机。
        """
        region = region.lower()
        if region == "random":
            region = _pick_random_profile_value(_REGIONS)
        if region not in _REGIONS:
            raise ValueError(f"unsupported region: {region!r}, choices: {list(_REGIONS.keys())}")

        # UA 的浏览器和系统优先级最高；不接受无法由现有三种 persona
        # 强一致表达的 Safari/iOS/其他 Chromium 衍生浏览器。
        if "Firefox/" in ua:
            engine = "firefox"
        elif "Edg/" in ua or "EdgA/" in ua:
            engine = "edge"
        elif "Chrome/" in ua or "Chromium/" in ua:
            engine = "chrome"
        else:
            raise ValueError("unsupported UA browser; expected Chrome, Edge or Firefox")

        # 识别平台
        if "iPhone" in ua or "iPad" in ua or "iPod" in ua:
            raise ValueError("iOS UA is not supported by the current browser kernels")
        if "Android" in ua:
            os_name = "android"
        elif "Macintosh" in ua:
            os_name = "mac"
        elif "Windows" in ua:
            os_name = "windows"
        elif "Linux" in ua or "X11" in ua:
            os_name = "linux"
        else:
            raise ValueError("unsupported UA operating system")

        obj = cls.__new__(cls)
        obj._browser = engine
        obj.engine = "chrome" if engine in ("chrome", "edge") else "firefox"
        obj.region = region
        obj.os = os_name

        reg = _REGIONS[region]
        obj._tz = reg["tz"]
        obj._locale = reg["locale"]
        obj._langs = reg["langs"]
        # 与普通 Profile 构造路径保持相同的正 int32 范围。
        obj._readback_seed = random.randint(1, 0x7FFFFFFF)

        device = obj._pick_device_for_ua(ua)
        screen_w, screen_h = device["screen"]
        avail_w, avail_h, avail_l, avail_t = obj._derive_avail(screen_w, screen_h)
        window = obj._derive_window(avail_w, avail_h, device["dpr"])
        gpu_vendor, gpu_renderer = device["gpu"]
        cores = device["cores"]
        capabilities = _capability_bundle(
            os_name, obj.engine, device, obj._locale
        )

        if obj.engine == "chrome":
            # Chrome token 描述 Chromium 版本，Edge token 描述 Edge 版本；
            # 两者分别保留，不能拿 Chrome token 冒充 Edge 完整版本。
            chrome_match = re.search(r"(?:Chrome|Chromium)/([\d.]+)", ua)
            chrome_ua_version = (
                chrome_match.group(1) if chrome_match else CHROME_RUNTIME_VERSION
            )
            chrome_major = chrome_ua_version.split(".", 1)[0]
            if (chrome_ua_version.endswith(".0.0.0")
                    or chrome_ua_version == chrome_major):
                info = _CHROME_VERSIONS.get(chrome_major)
                if info:
                    build, patches = info
                    chrome_full_ver = (
                        f"{chrome_major}.0.{build}.{random.choice(patches)}"
                    )
                else:
                    chrome_full_ver = chrome_ua_version
            else:
                chrome_full_ver = chrome_ua_version

            is_edge = engine == "edge"
            edge_ver = None
            if is_edge:
                edge_match = re.search(r"EdgA?/([\d.]+)", ua)
                edge_ua_version = edge_match.group(1)
                browser_major = edge_ua_version.split(".", 1)[0]
                edge_ver = edge_ua_version
                if (edge_ua_version.endswith(".0.0.0")
                        or edge_ua_version == browser_major):
                    edge_pool = (
                        _EDGE_ANDROID_VERSIONS if os_name == "android"
                        else _EDGE_DESKTOP_VERSIONS
                    )
                    edge_info = edge_pool.get(browser_major)
                    if edge_info:
                        edge_build, edge_patches = edge_info
                        edge_ver = (
                            f"{browser_major}.0.{edge_build}."
                            f"{random.choice(edge_patches)}"
                        )
            else:
                browser_major = chrome_major

            mi = int(chrome_major)
            gchars = [" ", "(", ":", "-", ".", "/", ")", ";", "=", "?", "_"]
            gvers = ["8", "99", "24"]
            grease_brand = f"Not{gchars[mi % 11]}A{gchars[(mi + 1) % 11]}Brand"
            grease_ver = gvers[mi % 3]
            orders = {0: (0, 1, 2), 1: (0, 2, 1), 2: (1, 0, 2),
                      3: (1, 2, 0), 4: (2, 0, 1), 5: (2, 1, 0)}
            if is_edge:
                base = [
                    {"brand": grease_brand, "version": f"{grease_ver}.0.0.0"},
                    {"brand": "Chromium", "version": chrome_full_ver},
                    {"brand": "Microsoft Edge", "version": edge_ver},
                ]
            else:
                base = [
                    {"brand": grease_brand, "version": f"{grease_ver}.0.0.0"},
                    {"brand": "Chromium", "version": chrome_full_ver},
                    {"brand": "Google Chrome", "version": chrome_full_ver},
                ]
            brands = [base[i] for i in orders[mi % 6]]

            if os_name == "android":
                pv = device["platform_version"]
            elif os_name == "windows":
                pv = random.choices(_WIN_PLATFORM_VERSIONS, _WIN_PLATFORM_WEIGHTS, k=1)[0]
            elif os_name == "mac":
                pv = device["platform_version"]
            else:
                pv = "6.8.0"

            obj.fingerprint = Fingerprint(
                user_agent=ua,
                ua_full_brands=brands,
                platform_version=pv,
                architecture=(
                    "" if os_name == "android" else
                    ("arm" if os_name == "mac" else "x86")
                ),
                model=device["model"] if os_name == "android" else "",
                mobile="Mobile" in ua,
                bitness=(
                    "" if os_name == "android"
                    else (
                        "64" if os_name in ("mac", "linux")
                        or any(token in ua for token in ("Win64", "x64", "WOW64"))
                        else "32"
                    )
                ),
                wow64="WOW64" in ua,
                hardware_concurrency=cores,
                accept_languages=_accept_language_q(obj._langs),
                locale=obj._locale,
                timezone=obj._tz,
                screen_width=screen_w,
                screen_height=screen_h,
                avail_width=avail_w,
                avail_height=avail_h,
                avail_left=avail_l,
                avail_top=avail_t,
                color_depth=obj._pick_color_depth(),
                device_memory=device.get("memory", 8),
                dpr=device["dpr"],
                max_touch_points=5 if os_name == "android" else 0,
                webgl_vendor=gpu_vendor,
                webgl_renderer=gpu_renderer,
                readback_seed=obj._readback_seed,
                **window,
                **capabilities,
            )
            obj.version = browser_major
            obj.full_version = edge_ver if is_edge else chrome_full_ver
        else:
            firefox_match = re.search(r"Firefox/([\d.]+)", ua)
            firefox_version = (
                firefox_match.group(1)
                if firefox_match else FIREFOX_RUNTIME_VERSION
            )
            major = firefox_version.split(".", 1)[0]
            obj.fingerprint = Fingerprint(
                user_agent=ua,
                platform="Linux armv81" if os_name == "android" else None,
                oscpu="Linux armv81" if os_name == "android" else None,
                app_version=ua.removeprefix("Mozilla/"),
                hardware_concurrency=cores,
                accept_languages=_accept_language_q(obj._langs),
                locale=obj._locale,
                timezone=obj._tz,
                screen_width=screen_w,
                screen_height=screen_h,
                avail_width=avail_w,
                avail_height=avail_h,
                avail_left=avail_l,
                avail_top=avail_t,
                color_depth=obj._pick_color_depth(),
                dpr=device["dpr"],
                max_touch_points=5 if os_name == "android" else 0,
                webgl_vendor=gpu_vendor,
                webgl_renderer=gpu_renderer,
                readback_seed=obj._readback_seed,
                **window,
                **capabilities,
            )
            obj.version = major
            obj.full_version = firefox_version

        obj.user_agent = ua
        return obj

    def __repr__(self):
        return f"Profile(browser={self._browser!r}, region={self.region!r}, ua={self.user_agent!r})"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zlib.py - Z-Library (Librella) 搜索 / 下载 CLI

只依赖 Python 标准库，无需任何第三方包。

用法:
    python zlib.py search   "逻辑学导论" [--limit 15] [--ext epub] [--lang zh] [--json]
    python zlib.py download "逻辑学导论 第15版" [--index 1] [--out DIR] [--force] [--dry-run]
    python zlib.py batch    wishlist.txt [--out DIR] [--rotate]
    python zlib.py quota [--all]
    python zlib.py domains [--refresh]
    python zlib.py accounts list|add|capture|remove|default ...

多账号:
    号池存在 skill 目录的 accounts.json（{"default": 别名, "accounts": [...]}）。
    --account 别名   指定用哪个号（search/download/batch/quota 均支持）
    --rotate         批量下载时在号池内轮换：额度用尽或风控(无直链)即切下一个号
    未指定 --account 时用号池 default；号池为空则回落到 env / 客户端 config.json。

退出码:
    0 成功 / 2 未找到匹配书籍 / 3 今日下载额度用尽 / 4 目标文件已存在 / 1 其他错误
"""

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 基础配置

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
DOMAIN_CACHE = os.path.join(SKILL_DIR, ".domain_cache.json")
ACCOUNTS_PATH = os.path.join(SKILL_DIR, "accounts.json")

DEFAULT_CONFIG = {
    # 默认落盘目录（用户书库）
    "library_dir": "books",
    # 文件名模板，可用 {title} {author} {year} {ext}
    "filename_template": "{title}{author_part}.{ext}",
    # 域名优先级（前面的先探测）
    "domains": [
        "zh.librella.fi",
        "librella.fi",
        "z-library.sk",
        "z-lib.fm",
        "z-lib.gl",
        "z-library.im",
    ],
    # 网络超时（秒）
    "timeout": 30,
    # 每日下载上限覆盖值（null＝用 API 返回值）。
    # 坑：会员账号 API profile 常返回旧免费额度 10，实际会员日限 20——
    # 服务器端按真实额度放行，本地检查若不覆盖会误判"额度用尽"。
    "daily_limit": None,
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 不校验 TLS（部分镜像证书链不完整）
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------- 工具函数

def eprint(*a):
    print(*a, file=sys.stderr)


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        eprint("[warn] 无法写入 %s: %s" % (path, e))


def get_config():
    cfg = dict(DEFAULT_CONFIG)
    user = load_json(CONFIG_PATH)
    if isinstance(user, dict):
        cfg.update({k: v for k, v in user.items() if v is not None})
    return cfg


def read_client_credentials():
    """只从 Z-Library 桌面客户端读取"当前登录"的那一份凭据。

    明文来源是 config.json；crd.json 是同一账号的 Chromium OSCrypt 加密副本，
    不可直接读取，也不可靠（不参与解析）。Cookies 库在新站点(.fi/.tw)下
    已不再保存 remix_userid/remix_userkey，故不作为凭据来源。
    """
    candidates = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(os.path.join(appdata, "z-library", "config.json"))
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "AppData", "Roaming", "z-library", "config.json"))
    for p in candidates:
        d = load_json(p)
        if d.get("remix_userid") and d.get("remix_userkey"):
            return str(d["remix_userid"]), str(d["remix_userkey"]), p
    return None, None, None


def find_credentials():
    """单账号凭据解析：env > 客户端 config.json > skill 目录 credential.json。"""
    uid = os.environ.get("ZLIB_USERID")
    key = os.environ.get("ZLIB_USERKEY")
    if uid and key:
        return str(uid), str(key), "env"

    candidates = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(os.path.join(appdata, "z-library", "config.json"))
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "AppData", "Roaming", "z-library", "config.json"))
    candidates.append(os.path.join(SKILL_DIR, "credential.json"))

    for p in candidates:
        d = load_json(p)
        if d.get("remix_userid") and d.get("remix_userkey"):
            return str(d["remix_userid"]), str(d["remix_userkey"]), p
    return None, None, None


# ---------------------------------------------------------------- 账号池

def load_accounts():
    d = load_json(ACCOUNTS_PATH)
    accs = d.get("accounts") or []
    if isinstance(accs, dict):  # 容错：允许 {别名: {userid,userkey}} 形式
        accs = [dict(v, alias=k) for k, v in accs.items()]
    return {"default": d.get("default"), "accounts": accs}


def save_accounts(d):
    seen, clean = set(), []
    for a in d.get("accounts") or []:
        al = str(a.get("alias") or "").strip()
        if not al or al in seen:
            continue
        seen.add(al)
        rec = {
            "alias": al,
            "userid": str(a.get("userid") or ""),
            "userkey": str(a.get("userkey") or ""),
            "note": a.get("note") or "",
        }
        for k in ("name", "daily_limit"):
            v = a.get(k)
            if v is not None and v != "":
                rec[k] = int(v) if k == "daily_limit" else v
        clean.append(rec)
    out = {"default": d.get("default") or (clean[0]["alias"] if clean else None),
           "accounts": clean}
    save_json(ACCOUNTS_PATH, out)
    return out


def get_account(alias):
    for a in load_accounts()["accounts"]:
        if a.get("alias") == alias:
            return a
    return None


def pool_aliases():
    return [a["alias"] for a in load_accounts()["accounts"]]


def usable_accounts():
    """号池中凭据完整、可用的账号。"""
    return [a for a in load_accounts()["accounts"]
            if a.get("userid") and a.get("userkey")]


def account_limit(cfg, user, alias=None):
    """某账号的有效每日额度（按优先级）。

    真实坑（2026-09-13 实测）：API profile 的 downloads_limit 对**会员号**
    固定返回旧免费值 10，服务器实际按 20 放行；而**免费号**返回的 10 就是真的。
    所以全局 daily_limit 覆盖只能对 isPremium 的账号生效，否则会把免费号
    误报成 20 本、本地放行到 20，直到服务端在第 11 本拒绝。

    优先级：号池 per-account daily_limit > （会员）全局 daily_limit > API 值。
    """
    a = get_account(alias) if alias else None
    # 注意用 is not None：daily_limit=0 是合法值（等于把这个号"停用"），
    # 用 truthy 判断会把 0 当成"未设置"而漏掉。
    if a and a.get("daily_limit") is not None:
        return int(a["daily_limit"])
    api_lim = user.get("downloads_limit") or 0
    if user.get("isPremium"):
        return cfg.get("daily_limit") or api_lim
    return api_lim


def account_chain(account=None, rotate=False):
    """返回按使用顺序排列的 [(alias, uid, key), ...]。

    - 指定 account（或无 account 但号池有 default）→ 走号池。
      rotate=True 时以起点为轴轮询其余账号；否则只用起点那一个。
    - 号池为空且未指定别名 → 回落到 env / 客户端 config.json（别名记 None）。
    """
    pool = load_accounts()
    accs = usable_accounts()
    start = account or pool.get("default")

    if start:
        if not accs:
            eprint("[error] 号池里没有任何可用账号（accounts.json 为空或无凭据）")
            return []
        aliases = [a["alias"] for a in accs]
        if start not in aliases:
            eprint("[error] 号池里没有别名「%s」（现有：%s）" % (start, "、".join(aliases)))
            return []
        i = aliases.index(start)
        order = aliases[i:] + aliases[:i]
        if not rotate:
            order = order[:1]
        by = {a["alias"]: a for a in accs}
        return [(al, by[al]["userid"], by[al]["userkey"]) for al in order]

    uid, key, _src = find_credentials()
    if not uid:
        eprint("[error] 未找到 Z-Library 凭据（号池为空，客户端 config.json 也没有）")
        return []
    return [(None, uid, key)]


def build_headers(uid, key, json_body=False, referer=None):
    h = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Cookie 才是真正生效的鉴权方式（实测 header 不足以通过下载接口）
        "Cookie": "remix_userid=%s; remix_userkey=%s; siteLanguage=zh" % (uid, key),
        "remix-userid": str(uid),
        "remix-userkey": str(key),
    }
    if json_body:
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        h["X-Requested-With"] = "XMLHttpRequest"
    if referer:
        h["Referer"] = referer
    return h


def http_request(url, headers, data=None, timeout=30, method=None):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return r.status, r.read()


# ---------------------------------------------------------------- 域名解析

def probe_domain(domain, timeout=12):
    url = "https://%s/eapi/info/ok" % domain
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            body = r.read(200)
            return r.status == 200 and b"success" in body
    except Exception:
        return False


def resolve_domain(cfg, refresh=False):
    """返回一个可用的站点域名，结果缓存到 .domain_cache.json。"""
    if not refresh:
        c = load_json(DOMAIN_CACHE)
        d = c.get("domain")
        # 缓存的域名 15 分钟内直接复用，避免每次都探测
        if d and time.time() - c.get("ts", 0) < 900:
            return d

    for d in cfg["domains"]:
        if probe_domain(d, timeout=10):
            save_json(DOMAIN_CACHE, {"domain": d, "ts": time.time()})
            return d
    raise RuntimeError(
        "无法连接任何 Z-Library 镜像。请检查网络/代理，或用 `domains --refresh` 重试。"
    )


# ---------------------------------------------------------------- API 封装

def api_search(domain, uid, key, query, limit=20, timeout=30):
    """POST /eapi/book/search  —— 注意：GET 形式会返回 400，必须用 POST。"""
    url = "https://%s/eapi/book/search" % domain
    body = urllib.parse.urlencode({"message": query}).encode("utf-8")
    headers = build_headers(uid, key, json_body=True, referer="https://%s/" % domain)
    status, raw = http_request(url, headers, data=body, timeout=timeout, method="POST")
    payload = json.loads(raw.decode("utf-8", "replace"))
    books = payload.get("books") or []
    if payload.get("success") != 1:
        raise RuntimeError(payload.get("error") or "搜索失败")
    return books[:limit]


def api_book_file(domain, uid, key, book_id, book_hash, timeout=30):
    """GET /eapi/book/{id}/{hash}/file —— 返回 CDN 直链。"""
    url = "https://%s/eapi/book/%s/%s/file" % (domain, book_id, book_hash)
    headers = build_headers(
        uid, key, referer="https://%s/book/%s" % (domain, book_id)
    )
    status, raw = http_request(url, headers, timeout=timeout)
    payload = json.loads(raw.decode("utf-8", "replace"))
    if payload.get("success") != 1:
        raise RuntimeError(payload.get("error") or "获取下载链接失败")
    return payload.get("file") or {}


def api_profile(domain, uid, key, timeout=20):
    url = "https://%s/eapi/user/profile/%s/%s" % (domain, uid, key)
    headers = build_headers(uid, key)
    status, raw = http_request(url, headers, timeout=timeout)
    return json.loads(raw.decode("utf-8", "replace"))


# ---------------------------------------------------------------- 匹配与命名

def norm(s):
    if not s:
        return ""
    s = str(s).lower()
    s = re.sub(r"[\(\)\[\]【】《》<>（）\s\-_·、,，.。:：;；!！?？\"'“”‘’/\\|]+", "", s)
    return s


def score_book(book, query, want_ext=None, want_lang=None):
    """给候选书打分，用于自动挑选最佳匹配。"""
    s = 0.0
    nq = norm(query)
    nt = norm(book.get("title"))
    na = norm(book.get("author"))
    nfull = nt + na + norm(book.get("publisher"))

    if nq and nt == nq:
        s += 100
    elif nq and nq in nt:
        s += 70
    elif nq and nt and nt in nq:
        s += 60
    if nq and nq in nfull:
        s += 15
    # 逐词命中率
    toks = [t for t in re.split(r"\s+", str(query).strip()) if t]
    if len(toks) > 1:
        hit = sum(1 for t in toks if norm(t) and norm(t) in nfull)
        s += 30.0 * hit / len(toks)

    ext = (book.get("extension") or "").lower()
    if want_ext:
        s += 25 if ext in [e.strip().lower() for e in want_ext.split(",")] else -40
    lang = book.get("language") or ""
    if want_lang:
        wl = want_lang.strip().lower()
        is_en = lang.lower().startswith("english")
        is_zh = lang.lower().startswith("chinese") or lang in ("中文",)
        if wl in ("zh", "cn", "chinese") and is_zh:
            s += 20
        elif wl in ("en", "english") and is_en:
            s += 20
        elif wl in (lang.lower(),):
            s += 15

    try:
        fs = float(book.get("filesize") or 0)
    except Exception:
        fs = 0
    # 电子书太小通常是残本；过大的扫描版优先度略降
    if 300_000 < fs < 60_000_000:
        s += 5
    return s


def pick_best(books, query, want_ext=None, want_lang=None):
    scored = [(score_book(b, query, want_ext, want_lang), b) for b in books]
    scored.sort(key=lambda x: -x[0])
    return scored


ILLEGAL = r'[<>:"/\\|?*\x00-\x1f]'


def sanitize(name, maxlen=110):
    name = re.sub(ILLEGAL, "_", str(name))
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip(" .")
    return name or "untitled"


def clean_author(author):
    """作者串常是 'A / B / C' 或 'A, B, C' 形式，只取首位并把长度压到合理范围。"""
    if not author:
        return ""
    a = re.split(r"\s*[/、;；|]\s*|\s*,\s*", str(author))[0].strip()
    a = re.sub(r"^\s*[\[【(（]\s*[^\]】)）]{1,6}\s*[\]】)）]\s*", "", a)  # 去掉 [美] 之类的国别前缀
    a = a.strip(" .·-")
    if len(a) > 24:
        a = a[:24].rstrip(" .·-")
    return a


def build_filename(book, cfg):
    title = book.get("title") or "untitled"
    author = clean_author(book.get("author"))
    ext = (book.get("extension") or "epub").lstrip(".")
    # 作者与书名高度重复时不重复标注
    author_part = ""
    if author and norm(author) not in norm(title) and norm(title) not in norm(author):
        author_part = " (%s)" % author
    name = cfg["filename_template"].format(
        title=title, author_part=author_part,
        year=book.get("year") or "", ext=ext,
    )
    # ⚠️ 长书名修复（2026-09-13 实测）：sanitize 的 110 字上限原来会把结尾扩展名一起砍掉，
    # 《大分流…》《阿特伍德作品集…》双双落盘成无扩展名文件。改为先截主干、扩展名永远保留。
    if ext and name.lower().endswith("." + ext.lower()):
        name = name[: -(len(ext) + 1)]
    cap = max(10, 110 - len(ext) - 1)
    stem = sanitize(name, maxlen=cap)
    # 截断若留下悬空的半括号（如 "…(彭慕兰"），从最后一个 "(" 起整段去掉，避免产出丑文件名
    if len(name) > cap and stem.count("(") != stem.count(")"):
        while stem.count("(") > stem.count(")"):
            i = stem.rfind("(")
            if i < 0:
                break
            stem = stem[:i].rstrip()
    return stem + "." + ext


def already_exists(out_dir, book):
    """按归一化标题做去重，避免重复下载占用每日额度。"""
    if not os.path.isdir(out_dir):
        return None
    nt = norm(book.get("title"))
    if not nt:
        return None
    for fn in os.listdir(out_dir):
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in (".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".fb2", ".txt"):
            continue
        ns = norm(stem)
        if not ns:
            continue
        # 去掉可能存在的中文全角括号作者名后再比较
        ns_head = re.split(r"[\(（]", ns)[0]
        if ns == nt or (len(nt) >= 6 and nt in ns) or (len(ns_head) >= 6 and ns_head == nt):
            return fn
    return None


# ---------------------------------------------------------------- 下载

def download_file(url, dest, timeout=180):
    headers = {"User-Agent": UA, "Accept": "*/*"}
    req = urllib.request.Request(url, headers=headers)
    tmp = dest + ".part"
    got = 0
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r, \
                open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    pct = got * 100 // total
                    sys.stderr.write("\r  下载中 %d%%  (%.1f/%.1f MB)" % (
                        pct, got / 1048576, total / 1048576))
                    sys.stderr.flush()
    except Exception:
        # 失败或中断时清掉半成品，避免留下 .part 垃圾
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if total:
        sys.stderr.write("\n")
    if got == 0:
        os.remove(tmp)
        raise RuntimeError("下载到 0 字节，链接可能已过期")
    os.replace(tmp, dest)
    return got


# ---------------------------------------------------------------- 子命令

def cmd_search(args):
    cfg = get_config()
    chain = account_chain(getattr(args, "account", None))
    if not chain:
        return 1
    alias, uid, key = chain[0]
    domain = resolve_domain(cfg)
    books = api_search(domain, uid, key, args.query, limit=args.limit,
                       timeout=cfg["timeout"])

    if args.ext or args.lang:
        ranked = pick_best(books, args.query, args.ext, args.lang)
        books = [b for _, b in ranked]

    if args.json:
        out = [{
            "id": b.get("id"), "title": b.get("title"), "author": b.get("author"),
            "year": b.get("year"), "publisher": b.get("publisher"),
            "language": b.get("language"), "extension": b.get("extension"),
            "filesizeString": b.get("filesizeString"), "hash": b.get("hash"),
            "score": round(score_book(b, args.query, args.ext, args.lang), 1),
        } for b in books]
        print(json.dumps({"domain": domain, "query": args.query, "count": len(out),
                          "books": out}, ensure_ascii=False, indent=1))
        return 0 if books else 2

    if not books:
        eprint("未找到「%s」相关书籍" % args.query)
        return 2

    print("站点: %s   账号: %s %s/%s   命中: %d 条" % (
        domain, "[%s]" % alias if alias else "", uid, key[:6] + "...", len(books)))
    print("-" * 96)
    for i, b in enumerate(books, 1):
        print("%2d. %s" % (i, b.get("title")))
        print("    %s | %s | %s | %s | %s | id=%s hash=%s" % (
            b.get("author") or "-", b.get("year") or "-",
            b.get("language") or "-", b.get("extension") or "-",
            b.get("filesizeString") or "-", b.get("id"), b.get("hash")))
    return 0


def cmd_download(args):
    cfg = get_config()
    chain = account_chain(getattr(args, "account", None))
    if not chain:
        return 1
    alias, uid, key = chain[0]
    domain = resolve_domain(cfg)

    prof = api_profile(domain, uid, key)
    _u = prof.get("user", {})
    used = _u.get("downloads_today", 0)
    limit = account_limit(cfg, _u, alias)
    left = (limit or 0) - (used or 0)
    eprint("[账号] %s" % (alias or "(客户端账号)"))
    eprint("[额度] 今日 %s/%s，剩余 %s" % (used, limit, left))

    books = api_search(domain, uid, key, args.query, limit=max(args.limit, 20),
                       timeout=cfg["timeout"])
    if not books:
        eprint("未找到「%s」相关书籍" % args.query)
        return 2

    ranked = pick_best(books, args.query, args.ext, args.lang)
    if args.dry_run:
        print("查询: %s" % args.query)
        for i, (sc, b) in enumerate(ranked[:5], 1):
            print("  %2d. [%.0f] %s | %s | %s | %s" % (
                i, sc, b.get("title"), b.get("extension"),
                b.get("filesizeString"), b.get("language")))
        return 0

    idx = max(1, min(args.index, len(ranked))) - 1
    score, book = ranked[idx]
    if score <= 0 and not args.force:
        eprint("没有足够置信的匹配（最高分 %.0f）。可加 --force 强制下载，或调整关键词。" % score)
        return 2

    out_dir = args.out or cfg["library_dir"]
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)

    dup = already_exists(out_dir, book)
    if dup and not args.force:
        print("[跳过] 已存在同书: %s" % dup)
        return 4

    if left <= 0 and not args.force:
        eprint("[中止] 今日下载额度已用尽（%s/%s）。" % (used, limit))
        return 3

    fname = build_filename(book, cfg)
    dest = os.path.join(out_dir, fname)
    eprint("[匹配] %s" % book.get("title"))
    eprint("[作者] %s   [年份] %s   [格式] %s   [大小] %s" % (
        book.get("author") or "-", book.get("year") or "-",
        book.get("extension"), book.get("filesizeString")))

    info = api_book_file(domain, uid, key, book.get("id"), book.get("hash"),
                         timeout=cfg["timeout"])
    link = info.get("downloadLink")
    if not link:
        eprint("[error] 接口未返回下载直链")
        return 1

    eprint("[保存] %s" % dest)
    size = download_file(link, dest, timeout=args.timeout)
    print("[完成] %s  (%.2f MB) %s" % (
        dest, size / 1048576, "[%s]" % alias if alias else ""))
    return 0


def cmd_batch(args):
    """按书单批量下载：每行一个书名，# 开头与空行忽略。

    多账号：--rotate 时在号池内轮换——当前账号额度用尽、或下载撞风控
    （接口不返回直链）时，自动切到下一个账号重试同一条书单。
    """
    cfg = get_config()
    chain = account_chain(getattr(args, "account", None),
                          rotate=getattr(args, "rotate", False))
    if not chain:
        return 1
    domain = resolve_domain(cfg)

    if not os.path.isfile(args.filelist):
        eprint("[error] 书单文件不存在: %s" % args.filelist)
        return 1
    with open(args.filelist, "r", encoding="utf-8-sig") as f:
        queries = [ln.strip() for ln in f
                   if ln.strip() and not ln.strip().startswith("#")]
    if args.max:
        queries = queries[:args.max]
    if not queries:
        eprint("书单为空")
        return 2

    out_dir = os.path.abspath(os.path.expanduser(args.out or cfg["library_dir"]))
    os.makedirs(out_dir, exist_ok=True)

    eprint("[书单] %d 条 -> %s" % (len(queries), out_dir))
    if len(chain) > 1:
        eprint("[号池] %d 个账号%s: %s" % (
            len(chain), "轮换" if args.rotate else "（不轮换，仅用首个）",
            " -> ".join(a[0] or "(client)" for a in chain)))
    stats = {"ok": 0, "skip": 0, "miss": 0, "fail": 0, "noquota": 0}
    done, failed = [], []
    per_account = {}
    cursor = 0

    for i, q in enumerate(queries, 1):
        eprint("\n[%d/%d] %s" % (i, len(queries), q))

        # 1) 找一个还有额度的账号（最多绕号池一圈）
        alias = uid = key = None
        for _ in range(len(chain)):
            alias, uid, key = chain[cursor % len(chain)]
            try:
                u = api_profile(domain, uid, key).get("user", {})
                dlim = account_limit(cfg, u, alias)
                left = dlim - (u.get("downloads_today") or 0)
            except Exception as e:
                eprint("  [%s] 额度查询失败: %s" % (alias or "client", e))
                left = 0
            if left > 0:
                break
            eprint("  [%s] 额度已用尽，切换下一个账号" % (alias or "client"))
            cursor += 1
        else:
            eprint("  [中止] 所有账号额度均已用尽")
            stats["noquota"] += 1
            break

        # 2) 用当前账号下载；撞风控(无直链)就换号重试同一本
        handled = False
        for attempt in range(len(chain)):
            alias, uid, key = chain[cursor % len(chain)]
            try:
                books = api_search(domain, uid, key, q, limit=max(args.limit, 20),
                                   timeout=cfg["timeout"])
                if not books:
                    eprint("  未找到")
                    stats["miss"] += 1
                    failed.append((q, "未找到"))
                    handled = True
                    break
                ranked = pick_best(books, q, args.ext, args.lang)
                score, book = ranked[0]
                if score <= 0 and not args.force:
                    eprint("  置信度不足（%.0f）" % score)
                    stats["miss"] += 1
                    failed.append((q, "置信度不足"))
                    handled = True
                    break

                dup = already_exists(out_dir, book)
                if dup and not args.force:
                    print("  [跳过] %s" % dup)
                    stats["skip"] += 1
                    handled = True
                    break

                info = api_book_file(domain, uid, key, book.get("id"), book.get("hash"),
                                     timeout=cfg["timeout"])
                link = info.get("downloadLink")
                if not link:
                    if attempt + 1 < len(chain):
                        eprint("  [%s] 无直链（疑似风控），切换下一个账号重试" % (alias or "client"))
                        cursor += 1
                        continue
                    eprint("  未取得直链（所有账号均失败）")
                    stats["fail"] += 1
                    failed.append((q, "无直链"))
                    handled = True
                    break

                dest = os.path.join(out_dir, build_filename(book, cfg))
                size = download_file(link, dest, timeout=args.timeout)
                who = alias or "client"
                print("  [完成] %s (%.2f MB) [%s]" % (
                    os.path.basename(dest), size / 1048576, who))
                stats["ok"] += 1
                per_account[who] = per_account.get(who, 0) + 1
                done.append(dest)
                handled = True
                break
            except Exception as e:
                eprint("  失败: %s" % e)
                stats["fail"] += 1
                failed.append((q, str(e)))
                handled = True
                break
        if not handled:
            stats["fail"] += 1
            failed.append((q, "全账号风控/无直链"))

    print("\n" + "=" * 60)
    print("成功 %d | 跳过 %d | 未找到 %d | 失败 %d%s" % (
        stats["ok"], stats["skip"], stats["miss"], stats["fail"],
        " | 额度用尽" if stats["noquota"] else ""))
    if per_account:
        print("各账号下载数: " + "  ".join(
            "%s=%d" % (k, v) for k, v in per_account.items()))
    for d in done:
        print("  + %s" % d)
    for q, why in failed:
        print("  - %s  (%s)" % (q, why))
    if args.json:
        print(json.dumps({"stats": stats, "per_account": per_account, "downloaded": done,
                          "failed": [{"query": q, "reason": w} for q, w in failed]},
                         ensure_ascii=False))
    if stats["noquota"]:
        return 3
    return 0 if (stats["ok"] or stats["skip"]) else 2


def cmd_quota(args):
    cfg = get_config()

    if getattr(args, "all", False):
        pool = load_accounts()
        if pool["accounts"]:
            chain = [(a["alias"], a["userid"], a["userkey"]) for a in pool["accounts"]
                     if a.get("userid") and a.get("userkey")]
        else:
            chain = account_chain()
        if not chain:
            return 1
        domain = resolve_domain(cfg)
        if args.json:
            out = []
            for alias, uid, key in chain:
                try:
                    u = api_profile(domain, uid, key).get("user", {})
                    out.append({"alias": alias, "id": u.get("id"), "name": u.get("name"),
                                "downloads_today": u.get("downloads_today"),
                                "downloads_limit": account_limit(cfg, u, alias),
                                "isPremium": u.get("isPremium")})
                except Exception as e:
                    out.append({"alias": alias, "id": uid, "error": str(e)})
            print(json.dumps({"domain": domain, "accounts": out}, ensure_ascii=False))
            return 0
        print("站点: %s" % domain)
        print("%-10s %-12s %-9s %-6s %s" % ("别名", "账号", "今日", "会员", "状态"))
        print("-" * 56)
        for alias, uid, key in chain:
            try:
                u = api_profile(domain, uid, key).get("user", {})
                lim = account_limit(cfg, u, alias)
                used = u.get("downloads_today")
                mark = "默认" if alias == pool.get("default") else ""
                print("%-10s %-12s %-9s %-6s %s" % (
                    alias or "(client)", u.get("name"), "%s/%s" % (used, lim),
                    "是" if u.get("isPremium") else "否",
                    ("剩 %s 本 %s" % ((lim or 0) - (used or 0), mark)) if lim else "?"))
            except Exception as e:
                print("%-10s %-12s %-9s %-6s %s" % (alias or "(client)", uid, "-", "-", "查询失败: %s" % e))
        return 0

    chain = account_chain(getattr(args, "account", None))
    if not chain:
        return 1
    alias, uid, key = chain[0]
    domain = resolve_domain(cfg)
    prof = api_profile(domain, uid, key)
    u = prof.get("user", {})
    if args.json:
        print(json.dumps({"domain": domain, "alias": alias, "id": u.get("id"),
                          "name": u.get("name"),
                          "downloads_today": u.get("downloads_today"),
                          "downloads_limit": account_limit(cfg, u, alias),
                          "isPremium": u.get("isPremium")}, ensure_ascii=False))
    else:
        print("站点     : %s" % domain)
        print("账号     : %s (id=%s)%s" % (
            u.get("name"), u.get("id"), "  别名 %s" % alias if alias else ""))
        print("今日额度 : %s / %s" % (u.get("downloads_today"),
              account_limit(cfg, u, alias)))
        print("会员     : %s" % ("是" if u.get("isPremium") else "否（免费账号每日 10 本）"))
    return 0


def cmd_accounts(args):
    """管理多账号池（accounts.json）。"""
    act = args.action
    pool = load_accounts()

    if act == "list":
        if not pool["accounts"]:
            print("号池为空。用 `accounts capture <别名>`（先登录客户端）或 "
                  "`accounts add <别名> --userid U --userkey K` 添加。")
            return 0
        print("默认账号: %s" % (pool.get("default") or "-"))
        print("-" * 72)
        dom = None
        for a in pool["accounts"]:
            tag = "  (默认)" if a["alias"] == pool.get("default") else ""
            line = "%-6s id=%-10s 名=%-12s %s%s" % (
                a["alias"], a["userid"], a.get("name") or "?", a.get("note") or "", tag)
            if args.probe:
                try:
                    if dom is None:
                        dom = resolve_domain(get_config())
                    u = api_profile(dom, a["userid"], a["userkey"]).get("user", {})
                    lim = account_limit(get_config(), u, a["alias"])
                    line += "   → %s / %s  会员:%s  %s" % (
                        u.get("downloads_today"), lim,
                        "是" if u.get("isPremium") else "否", u.get("name"))
                except Exception as e:
                    line += "   → 查询失败: %s" % e
            print(line)
        return 0

    if act in ("add", "capture"):
        alias = args.alias
        uid, key = args.userid, args.userkey
        src = "参数"
        if act == "capture" or args.from_client:
            cid, ckey, csrc = read_client_credentials()
            if not cid:
                eprint("[error] 客户端 config.json 里没有凭据；请先在 Z-Library 客户端登录该账号")
                return 1
            uid, key, src = cid, ckey, csrc
            if not alias:
                alias = "acct%d" % (len(pool["accounts"]) + 1)
        if not alias:
            eprint("[error] 请给出别名，如 `accounts add main`")
            return 1
        if not (uid and key):
            eprint("[error] 需要 --userid/--userkey，或用 --from-client 从客户端抓取")
            return 1

        # 查重：同一个 userid 已经挂在别的别名下面
        dup = [a["alias"] for a in pool["accounts"]
               if a["userid"] == uid and a["alias"] != alias]
        if dup:
            print("[重复] 这个号 (id=%s) 已经在池子里了，别名：%s" % (uid, "、".join(dup)))
            print("       本次不重复添加。若要改用新别名，先 `accounts remove %s`。" % "、".join(dup))
            return 0

        # 顺手取一次账号名，方便日后一眼认出哪个号是哪个
        uname = ""
        try:
            uname = api_profile(resolve_domain(get_config()), uid, key
                                ).get("user", {}).get("name") or ""
        except Exception as e:
            eprint("[warn] 取账号名失败（不影响入池）: %s" % e)

        ex = get_account(alias)
        if ex:
            ex.update({"userid": uid, "userkey": key})
            if args.note:
                ex["note"] = args.note
            if uname:
                ex["name"] = uname
            msg = "已更新"
        else:
            rec = {"alias": alias, "userid": uid, "userkey": key, "note": args.note or ""}
            if uname:
                rec["name"] = uname
            pool["accounts"].append(rec)
            msg = "已添加"
        if not pool.get("default"):
            pool["default"] = alias
        save_accounts(pool)
        print("[%s] %-6s id=%-10s 名=%-12s 来源:%s" % (msg, alias, uid, uname or "?", src))
        return 0

    if act == "remove":
        before = len(pool["accounts"])
        pool["accounts"] = [a for a in pool["accounts"] if a["alias"] != args.alias]
        if len(pool["accounts"]) == before:
            eprint("[error] 号池里没有别名「%s」" % args.alias)
            return 1
        if pool.get("default") == args.alias:
            pool["default"] = pool["accounts"][0]["alias"] if pool["accounts"] else None
        save_accounts(pool)
        print("[已删除] %s" % args.alias)
        return 0

    if act == "default":
        if not get_account(args.alias):
            eprint("[error] 号池里没有别名「%s」" % args.alias)
            return 1
        pool["default"] = args.alias
        save_accounts(pool)
        print("[默认账号] %s" % args.alias)
        return 0

    eprint("未知操作: %s" % act)
    return 1


def cmd_domains(args):
    cfg = get_config()
    print("探测可用镜像 ...")
    alive = []
    for d in cfg["domains"]:
        ok = probe_domain(d)
        print("  %-22s %s" % (d, "可用" if ok else "不可用"))
        if ok:
            alive.append(d)
    if alive:
        save_json(DOMAIN_CACHE, {"domain": alive[0], "ts": time.time()})
        print("\n当前使用: %s" % alive[0])
    else:
        print("\n没有可用镜像")
    return 0 if alive else 1


# ---------------------------------------------------------------- 入口

def main():
    # 行缓冲，保证 stdout 与 stderr 的进度信息在管道中也能按顺序出现
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    p = argparse.ArgumentParser(
        description="Z-Library 搜索与下载（多账号号池 CLI）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("search", help="搜索书籍")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=15)
    sp.add_argument("--ext", help="按格式过滤/加权，如 epub 或 epub,pdf")
    sp.add_argument("--lang", help="zh 或 en")
    sp.add_argument("--account", help="使用号池中的某个别名")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_search)

    dp = sub.add_parser("download", help="搜索并下载匹配度最高的一本")
    dp.add_argument("query")
    dp.add_argument("--index", type=int, default=1, help="选第 N 个匹配（1 起）")
    dp.add_argument("--out", help="保存目录，默认取 config.json 的 library_dir")
    dp.add_argument("--ext", help="偏好格式，如 epub / pdf")
    dp.add_argument("--lang", help="偏好语言，zh / en")
    dp.add_argument("--limit", type=int, default=20)
    dp.add_argument("--timeout", type=int, default=300, help="下载超时秒数")
    dp.add_argument("--account", help="使用号池中的某个别名")
    dp.add_argument("--force", action="store_true", help="忽略去重与额度检查")
    dp.add_argument("--dry-run", action="store_true", help="只列出候选，不下载")
    dp.set_defaults(func=cmd_download)

    bp = sub.add_parser("batch", help="按书单文件批量下载（每行一个书名）")
    bp.add_argument("filelist")
    bp.add_argument("--out", help="保存目录")
    bp.add_argument("--ext", help="偏好格式，如 epub / pdf")
    bp.add_argument("--lang", help="偏好语言，zh / en")
    bp.add_argument("--limit", type=int, default=20)
    bp.add_argument("--max", type=int, help="最多处理前 N 条")
    bp.add_argument("--timeout", type=int, default=300)
    bp.add_argument("--account", help="起始账号别名（配合 --rotate 决定轮换起点）")
    bp.add_argument("--rotate", action="store_true",
                    help="多账号轮换：额度用尽或撞风控时自动切下一个号")
    bp.add_argument("--force", action="store_true")
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_batch)

    qp = sub.add_parser("quota", help="查看账号与今日下载额度")
    qp.add_argument("--account", help="查询号池中某个别名")
    qp.add_argument("--all", action="store_true", help="列出号池全部账号的额度")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quota)

    ac = sub.add_parser("accounts", help="管理多账号池（list/add/capture/remove/default）")
    ac.add_argument("action", choices=["list", "add", "capture", "remove", "default"])
    ac.add_argument("alias", nargs="?", help="账号别名")
    ac.add_argument("--userid", help="手动指定 userid")
    ac.add_argument("--userkey", help="手动指定 userkey")
    ac.add_argument("--note", help="备注（如：会员/小号）")
    ac.add_argument("--from-client", action="store_true",
                    help="从客户端 config.json 抓取当前登录凭据")
    ac.add_argument("--probe", action="store_true", help="list 时逐个查询额度与会员状态")
    ac.set_defaults(func=cmd_accounts)

    mp = sub.add_parser("domains", help="探测可用镜像域名")
    mp.add_argument("--refresh", action="store_true")
    mp.set_defaults(func=cmd_domains)

    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        eprint("\n已中断")
        return 1
    except urllib.error.HTTPError as e:
        eprint("[HTTP %s] %s" % (e.code, e.reason))
        return 1
    except Exception as e:
        eprint("[error] %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

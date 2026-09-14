#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 ZCode/Agent 使用的安全检索入口。

只提供搜索与候选排序，不负责下载。复用 zlib_cli.py 的配置、凭据解析和搜索逻辑，
但在任何网络请求发生前恢复 Python 默认 TLS 证书与主机名校验，并且绝不输出 userkey。
"""

import argparse
import json
import ssl
import sys

import zlib_cli as legacy

# 原脚本为了兼容部分镜像关闭了 TLS 校验。Agent 入口强制覆盖为安全默认值。
legacy._SSL_CTX = ssl.create_default_context()


def book_record(rank, score, book):
    return {
        "rank": rank,
        "score": round(score, 1),
        "id": book.get("id"),
        "hash": book.get("hash"),
        "title": book.get("title"),
        "author": book.get("author"),
        "year": book.get("year"),
        "publisher": book.get("publisher"),
        "language": book.get("language"),
        "extension": book.get("extension"),
        "filesize": book.get("filesize"),
        "filesizeString": book.get("filesizeString"),
        "isbn": book.get("isbn"),
    }


def search(args):
    cfg = legacy.get_config()
    chain = legacy.account_chain(getattr(args, "account", None))
    if not chain:
        return 1

    alias, uid, key = chain[0]
    domain = legacy.resolve_domain(cfg, refresh=args.refresh_domain)
    books = legacy.api_search(
        domain,
        uid,
        key,
        args.query,
        limit=args.limit,
        timeout=cfg.get("timeout", 30),
    )
    ranked = legacy.pick_best(books, args.query, args.ext, args.lang)
    records = [
        book_record(i, score, book)
        for i, (score, book) in enumerate(ranked, 1)
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "domain": domain,
                    "account": alias or "本地凭据",
                    "query": args.query,
                    "preferred_extension": args.ext,
                    "preferred_language": args.lang,
                    "count": len(records),
                    "books": records,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if records else 2

    if not records:
        print("未找到相关书籍", file=sys.stderr)
        return 2

    print(
        "站点: %s   账号: %s   优先格式: %s   命中: %d 条"
        % (domain, alias or "本地凭据", args.ext or "不限", len(records))
    )
    print("-" * 96)
    for item in records:
        print("%2d. [%.0f] %s" % (item["rank"], item["score"], item["title"] or "-"))
        print(
            "    %s | %s | %s | %s | %s | %s"
            % (
                item["author"] or "-",
                item["year"] or "-",
                item["publisher"] or "-",
                item["language"] or "-",
                item["extension"] or "-",
                item["filesizeString"] or "-",
            )
        )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="ZCode/Agent 安全检索入口，默认优先 EPUB，只搜索不下载。"
    )
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--ext", default="epub", help="偏好格式，默认 epub；传空字符串可取消偏好")
    parser.add_argument("--lang", help="偏好语言，如 zh / en")
    parser.add_argument("--account", help="使用账号池中的别名")
    parser.add_argument("--refresh-domain", action="store_true", help="忽略域名缓存并重新探测")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        return search(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print("[error] %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

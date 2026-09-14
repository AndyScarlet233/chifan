#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输出当前 Skill 的默认下载目录。

优先读取 config.json 的 library_dir；相对路径按 Skill 根目录解析。
如果没有配置，则回落到用户 Downloads 目录。
"""

import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_ROOT / "config.json"


def main():
    configured = None
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            configured = data.get("library_dir")
        except (OSError, ValueError, TypeError):
            configured = None

    if configured:
        path = Path(str(configured)).expanduser()
        if not path.is_absolute():
            path = SKILL_ROOT / path
    else:
        path = Path.home() / "Downloads"

    print(path.resolve())


if __name__ == "__main__":
    main()

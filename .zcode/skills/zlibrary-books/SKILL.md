---
name: zlibrary-books
description: 当用户需要搜索、比较或核对电子书版本时使用。默认优先 EPUB。优先通过 Z-Library 安全检索入口读取 JSON 候选，比较书名、作者、年份、出版社、语言、格式、大小和匹配分；主检索无结果时，可参考配置中的备用书目源继续核对元数据。不得输出 remix_userkey。
metadata:
  author: AndyScarlet233
  version: "0.3.0"
---

# 中文电子书检索 Skill

推荐把本 Skill 安装到 ZCode 用户级目录 `~/.zcode/skills/zlibrary-books/`，这样可以在任意工作区使用。仓库内 `.zcode/skills/zlibrary-books/` 的副本主要用于开发和测试。

## 工具位置

如果当前工作区存在 `scripts/zlib_agent.py`，优先使用当前工作区版本；否则使用全局安装位置：

```text
~/.zcode/skills/zlibrary-books/scripts/zlib_agent.py
```

Windows PowerShell 示例：

```powershell
python "$HOME/.zcode/skills/zlibrary-books/scripts/zlib_agent.py" "<查询词>" --json
```

Linux/macOS 只有 `python3` 时，把 `python` 改成 `python3`。

## 默认规则

默认优先 EPUB。用户明确要求 PDF、MOBI 等其他格式时才覆盖。

找书时不要把第一条结果直接当成正确版本。优先给用户 3～5 个候选。判断可靠度时至少检查书名、作者、年份、出版社、语言、格式、文件大小和 `score`。如果版次、译者、出版社或年份无法确认，要明确说明不确定。

不得输出、复述或总结 `remix_userkey`。不要读取并展示 `accounts.json` 或 `credential.json` 的密钥内容。不要关闭 TLS 校验，不要自动使用 `--force` 或多账号轮换。

请只帮助用户检索其有权访问的内容，并遵守所在地法律、版权规定和相关服务条款。

## 搜索流程

用户说“帮我找某本书”“找最可靠的 EPUB”“比较几个版本”时：

1. 从用户描述中整理搜索词。已知作者、版次、年份或出版社时，把最有区分度的信息一起写入查询。
2. 运行安全检索入口并读取 JSON。
3. 默认已经优先 EPUB。用户要求 PDF 时加 `--ext pdf`。
4. 结合 `rank` 与 `score` 判断，但不要只看分数。
5. 向用户展示最值得考虑的 3～5 个候选，至少包括书名、作者、年份、出版社、语言、格式和大小，并简要说明可靠或可疑之处。

## 主检索不可用时

如果出现连接失败，可重新探测：

```powershell
python "$HOME/.zcode/skills/zlibrary-books/scripts/zlib_agent.py" "<查询词>" --json --refresh-domain
```

如果主检索仍无结果或版本信息不足，可以参考 `config.json` 中 `bibliographic_fallbacks` 配置的备用书目源，只用于核对书名、作者、出版社、年份、ISBN、语言和格式等元数据。备用来源之间信息冲突时，应把冲突告诉用户，不要擅自认定某一版本正确。

## 默认目录

用户明确指定保存位置时，优先使用用户给出的可写目录。用户没有指定时，读取本地 `config.json` 的 `library_dir`。

通过仓库的 Windows 安装脚本首次安装为全局 Skill 时，这个值会自动设成当前用户的 `Downloads` 目录，通常类似：

```text
C:\Users\用户名\Downloads
```

可运行辅助脚本查看当前默认目录：

```powershell
python "$HOME/.zcode/skills/zlibrary-books/scripts/显示下载目录.py"
```

本 Skill 的安全 Agent 入口主要负责检索和版本判断。需要保存用户有权获取的文件时，应尊重用户指定目录；不要默认把文件写进代码仓库。

## 首次配置

如果提示缺少凭据，不要要求用户把 `remix_userkey` 发到聊天里。Windows 用户可先在 Z-Library 桌面客户端登录自己的账号，再由用户本人完成本地账号配置；也可以使用环境变量 `ZLIB_USERID` 与 `ZLIB_USERKEY`。

## 候选质量判断

更可靠的候选通常具备：书名与用户要求高度一致，作者一致，特定版次时年份、出版社或译者信息吻合，默认优先 EPUB，文件大小不是异常的小文件，语言符合用户要求。

`score` 只是辅助指标，不是版本真实性证明。遇到同名书、合集、教材不同版次或译著不同译本时，要保守处理。

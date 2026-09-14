# Z-Library 中文检索工具

这是一个面向中文用户的轻量级 Z-Library eAPI 工具，也可以作为 ZCode 项目级 Skill 使用。它不需要浏览器自动化，也不需要安装第三方 Python 包。

当前最推荐的用途是：让 AI 先检索、比较和核对电子书候选，再把最可靠的几个版本交给用户选择，而不是让 Agent 自动下载第一条结果。

## ZCode 安全检索入口

仓库新增了：

```text
scripts/zlib_agent.py
.zcode/skills/zlibrary-books/SKILL.md
```

`scripts/zlib_agent.py` 是专门给 ZCode/Agent 使用的安全检索入口。它只负责搜索和候选排序，不执行下载，并会在任何网络请求发生前强制恢复 Python 默认 TLS 证书与主机名校验。

把仓库作为 ZCode 工作区打开后，进入“设置 → 技能”，刷新并启用 `zlibrary-books` 即可。ZCode 项目级 Skill 的目录正是：

```text
<workspace>/.zcode/skills/<skill-name>/SKILL.md
```

之后可以直接对 Agent 说：

```text
帮我找《三体》的 EPUB，列出最可靠的几个版本供我选择。
```

Agent 会调用：

```bash
python scripts/zlib_agent.py "三体 刘慈欣" --json
```

默认优先 EPUB。如果用户明确要求 PDF，则使用：

```bash
python scripts/zlib_agent.py "书名 作者" --ext pdf --json
```

## 内置候选域名

`config.json` 已经内置多个 Z-Library/Librella eAPI 候选域名，目前包括：

- `zh.librella.fi`
- `librella.fi`
- `z-library.sk`
- `z-lib.fm`
- `z-lib.gl`
- `z-library.im`

程序会自动探测可用地址，所以正常使用时不需要每次访问网页。安全检索入口会使用系统 CA 和主机名校验，证书异常的镜像会被视为不可用，而不是关闭 TLS 验证。

## 默认 EPUB

ZCode 安全检索入口默认使用 EPUB 作为偏好格式。`config.json` 也记录了：

```json
"preferred_extension": "epub"
```

旧版 `scripts/zlib_cli.py` 仍保留，主要用于兼容原项目的手动 CLI 工作流。因为它原本包含兼容性较强、但安全边界更宽的实现，ZCode Skill 不会调用它的下载功能。

## 候选排序

安全检索入口复用原项目的候选评分逻辑，并统一输出 JSON。AI 可以看到：

- 书名
- 作者
- 年份
- 出版社
- 语言
- 格式
- 文件大小
- 匹配分
- eAPI 图书 id / hash

`score` 只作为辅助判断，不代表版本一定正确。教材、译著、合集和不同版次应同时核对作者、年份、出版社、译者等信息。

## 快速测试

```bash
python scripts/zlib_agent.py --help
python scripts/zlib_agent.py "三体 刘慈欣" --json
```

Linux/macOS 只有 `python3` 时，把 `python` 换成 `python3`。

## 凭据

eAPI 使用 `remix_userid` 和 `remix_userkey`。其中 `remix_userkey` 应按账号密码处理，不要提交到 GitHub，也不要粘贴到公开聊天中。

安全检索入口复用原 CLI 的本地凭据来源，但不会输出 userkey。现有 `.gitignore` 会排除 `accounts.json` 与 `credential.json`。

推荐优先使用环境变量或由用户本人在本地完成账号配置，不要让 AI 要求用户在聊天里发送密钥。

## 安全说明

目前给 ZCode 的 Agent 路径已经做了这些保护：

- 强制恢复 HTTPS 证书校验
- 不输出 `remix_userkey`
- 默认只搜索，不自动下载
- 不自动使用 `--force`
- 不自动使用多账号轮换
- 用户选择版本之前只展示候选

原 `scripts/zlib_cli.py` 仍作为兼容代码保留；后续如果继续维护，建议逐步把安全修复迁回原 CLI，再删除兼容层。

## 使用边界

本项目只是客户端工具。请只检索和访问你有权获取的内容，并遵守所在地法律、版权规定和相关服务条款。

# 中文电子书检索工具

这是一个面向中文用户的轻量级电子书检索工具，也可以作为 ZCode 用户级 Skill 使用。当前推荐用途是：让 AI 先检索、比较和核对候选版本，再把最可靠的几个结果交给用户选择，而不是把第一条结果直接当成正确版本。

运行时只依赖 Python 标准库，不需要浏览器自动化，也不需要安装额外 Python 包。

## 推荐：安装为 ZCode 全局 Skill

ZCode 官方支持用户级技能目录：

```text
~/.zcode/skills/<skill-name>/SKILL.md
```

本仓库提供 Windows 安装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\安装ZCode全局技能.ps1
```

脚本会把 Skill、检索脚本和配置复制到：

```text
~/.zcode/skills/zlibrary-books/
```

首次安装时，默认目录会自动设为当前 Windows 用户的 Downloads 文件夹，通常类似：

```text
C:\Users\用户名\Downloads
```

再次运行安装脚本会更新 Skill 和脚本，但保留已有的本地 `config.json`，避免覆盖用户自己的目录和偏好设置。

安装完成后，在 ZCode 中进入“设置 → 技能”，点击刷新并启用 `zlibrary-books`。之后无论打开哪个项目，都可以调用这个 Skill。

## 安全检索入口

核心 Agent 入口是：

```text
scripts/zlib_agent.py
```

它只负责搜索和候选排序，并会在网络请求发生前恢复 Python 默认 TLS 证书与主机名校验。它不会输出 `remix_userkey`。

项目工作区中可直接运行：

```bash
python scripts/zlib_agent.py "三体 刘慈欣" --json
```

全局安装后，在 Windows PowerShell 中可运行：

```powershell
python "$HOME/.zcode/skills/zlibrary-books/scripts/zlib_agent.py" "三体 刘慈欣" --json
```

默认优先 EPUB。如果用户明确要求 PDF：

```powershell
python "$HOME/.zcode/skills/zlibrary-books/scripts/zlib_agent.py" "书名 作者" --ext pdf --json
```

## 主检索地址

`config.json` 内置多个 Z-Library/Librella eAPI 候选域名：

- `zh.librella.fi`
- `librella.fi`
- `z-library.sk`
- `z-lib.fm`
- `z-lib.gl`
- `z-library.im`

程序会自动探测可用地址，所以正常检索时不需要手动访问网页。证书异常的镜像会被安全检索入口视为不可用，而不是关闭 TLS 验证。

## 备用书目源

配置中增加了 `bibliographic_fallbacks`。当前记录了 Anna's Archive 的三个公开域名：

- `annas-archive.gl`
- `annas-archive.pk`
- `annas-archive.gd`

这些地址只作为主检索失败时的备用书目信息来源，用来核对书名、作者、出版社、年份、ISBN、语言和格式等元数据。项目不为这些备用源实现自动下载流程。

如果多个来源的信息互相冲突，AI 应把冲突明确告诉用户，而不是自行断定某个版本一定正确。

## 默认 EPUB

`config.json` 默认记录：

```json
"preferred_extension": "epub"
```

AI 判断候选时还应同时查看作者、年份、出版社、语言和文件大小。`score` 只是辅助指标，教材不同版次、译著不同译本、合集和同名书都需要额外核对。

## 下载目录

项目开发模式默认仍使用仓库里的 `books` 目录，方便调试；安装为 ZCode 全局 Skill 后，首次安装会把用户级配置的 `library_dir` 改成当前用户的 Downloads 文件夹。

查看当前默认目录：

```powershell
python "$HOME/.zcode/skills/zlibrary-books/scripts/显示下载目录.py"
```

如果用户在对话中明确指定其它目录，AI 应优先使用用户指定的可写位置，而不是固定保存到代码仓库。

## 凭据

eAPI 使用 `remix_userid` 和 `remix_userkey`。其中 `remix_userkey` 应按账号密码处理，不要提交到 GitHub，也不要粘贴到公开聊天中。

推荐优先使用环境变量或由用户本人在本地完成账号配置。现有 `.gitignore` 会排除 `accounts.json`、`credential.json`、`credentials/` 和常见密钥文件。

## 安全说明

给 ZCode 的 Agent 路径当前遵循这些规则：

- 使用系统 CA 和主机名校验
- 不输出 `remix_userkey`
- 默认先搜索和比较版本
- 不自动使用 `--force`
- 不自动使用多账号轮换
- 主检索失败时，备用来源只用于书目核对
- 用户指定保存目录时优先尊重用户选择

原 `scripts/zlib_cli.py` 仍作为兼容代码保留；后续如果继续维护，建议逐步把安全修复迁回原 CLI，再删除兼容层。

## 使用边界

请只检索和访问你有权获取的内容，并遵守所在地法律、版权规定和相关服务条款。

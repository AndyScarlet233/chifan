---
name: zlibrary-books
description: 当用户需要搜索、比较或核对 Z-Library 电子书版本时使用。默认优先 EPUB。通过安全检索入口读取 JSON 候选，比较书名、作者、年份、出版社、语言、格式、大小和匹配分，再把最可靠的 3～5 个候选交给用户选择。此 Skill 只负责检索与版本判断，不自动下载，也不得输出 remix_userkey。
metadata:
  author: AndyScarlet233
  version: "0.2.1"
---

# Z-Library 中文检索 Skill

本 Skill 使用当前工作区中的 `scripts/zlib_agent.py`。这个入口专门给 ZCode/Agent 使用，只做搜索和候选排序，不执行下载，并在网络请求前强制恢复 Python 默认 TLS 证书与主机名校验。

## 默认规则

默认优先 EPUB。用户明确要求 PDF、MOBI 等其他格式时才覆盖。

找书时先搜索，不要把第一条结果直接当成正确版本。优先给用户 3～5 个候选。判断可靠度时至少检查书名、作者、年份、出版社、语言、格式、文件大小和 `score`。如果版次、译者、出版社或年份无法确认，要明确说明不确定。

不得输出、复述或总结 `remix_userkey`。不要读取并展示 `accounts.json` 或 `credential.json` 的密钥内容。不要关闭 TLS 校验，不要调用旧 CLI 的下载、`--force` 或 `--rotate` 功能。

请只帮助用户检索其有权访问的内容，并遵守所在地法律、版权规定和服务条款。

## 搜索流程

用户说“帮我找某本书”“找最可靠的 EPUB”“比较几个版本”时：

1. 从用户描述中整理搜索词。已知作者、版次、年份或出版社时，把最有区分度的信息一起写入查询。
2. 运行：

```bash
python scripts/zlib_agent.py "<查询词>" --json
```

Linux/macOS 只有 `python3` 时改用：

```bash
python3 scripts/zlib_agent.py "<查询词>" --json
```

3. 默认已经优先 EPUB。用户要求 PDF 时加 `--ext pdf`。
4. 读取 `books` 数组，结合 `rank` 与 `score` 判断，但不要只看分数。
5. 向用户展示最值得考虑的 3～5 个候选，至少包括书名、作者、年份、出版社、语言、格式和大小，并简要说明可靠或可疑之处。
6. 用户选择后，只记录其选择并告诉用户对应候选；本 Skill 不自动下载。

## 域名问题

如果出现连接失败，可重新探测：

```bash
python scripts/zlib_agent.py "<查询词>" --json --refresh-domain
```

只使用仓库 `config.json` 中配置的候选 eAPI 域名。全部不可用时，告诉用户检查网络或稍后重试，不要关闭 TLS 验证。

## 首次配置

如果提示缺少凭据，不要要求用户把 `remix_userkey` 发到聊天里。Windows 用户可先在 Z-Library 桌面客户端登录自己的账号，再由用户本人运行原 CLI 的本地账号捕获命令；也可以使用环境变量 `ZLIB_USERID` 与 `ZLIB_USERKEY`。

## 候选质量判断

更可靠的候选通常具备：

- 书名与用户要求高度一致
- 作者一致
- 特定版次时，年份、出版社或译者信息吻合
- 默认优先 EPUB
- 文件大小不是异常的小文件
- 语言符合用户要求

`score` 只是辅助指标，不是版本真实性证明。遇到同名书、合集、教材不同版次或译著不同译本时，要保守处理。

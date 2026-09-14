---
name: zlibrary-books
description: 当用户需要搜索、比较或核对 Z-Library 电子书版本，或在明确选定版本后请求下载时使用。默认优先 EPUB。先用 JSON 搜索结果比较书名、作者、年份、出版社、语言、格式和大小，再把可靠候选交给用户选择；未得到明确选择前不要下载。不得输出 remix_userkey 或把凭据写入对话。
metadata:
  author: AndyScarlet233
  version: "0.2.0"
---

# Z-Library 中文检索 Skill

这个 Skill 使用当前工作区的 `scripts/zlib_cli.py`。如果脚本不存在，不要猜测命令或自动从未知来源下载代码，应告诉用户先打开或克隆本仓库。

## 默认原则

默认格式是 EPUB。用户明确要求 PDF、MOBI 等其他格式时才覆盖。

找书时先搜索，不要直接下载第一条结果。优先把 3～5 个可靠候选交给用户选择。判断可靠度时至少查看书名、作者、年份、出版社、语言、格式、文件大小和 `score`。如果版次、译者、出版社或年份对任务重要，而搜索结果不能确认，就明确说明不确定，不要擅自判断。

不得在回复、日志总结或命令展示中输出 `remix_userkey`。不要读取并复述 `accounts.json` 或 `credential.json` 的密钥内容。不要为了兼容某个镜像关闭 TLS 证书校验。

不要自动启用 `--force`。不要自动启用 `--rotate`，也不要把多账号轮换作为规避服务限制的方法。

请只帮助用户访问其有权获取的内容，并遵守所在地法律、版权规定和服务条款。

## 工作流一：找书

用户说“帮我找某本书”“找最可靠的 EPUB”“比较几个版本”时：

1. 从用户描述中整理搜索词。已知作者、版次、年份或出版社时，把最有区分度的信息一起放入查询。
2. 运行：

```bash
python scripts/zlib_cli.py search "<查询词>" --json
```

如果系统只有 `python3`，改用：

```bash
python3 scripts/zlib_cli.py search "<查询词>" --json
```

3. 默认已经优先 EPUB，不需要重复加 `--ext epub`。用户要求 PDF 时加 `--ext pdf`；用户要求不限格式时加 `--ext any`。
4. 读取 `books` 数组，按 `rank` 和 `score` 评估，但不要只看分数。
5. 向用户展示最值得考虑的 3～5 个候选。至少给出书名、作者、年份、出版社、语言、格式、大小；说明为什么更可靠或哪里仍有疑点。
6. 等待用户选择。

## 工作流二：用户选择后下载

用户明确选择“第 N 个”后，使用与搜索完全相同的查询词和格式偏好：

```bash
python scripts/zlib_cli.py download "<查询词>" --index N --dry-run --json
```

先确认 `--dry-run` 中的第 N 个仍然是用户选中的版本。确认一致后再运行：

```bash
python scripts/zlib_cli.py download "<查询词>" --index N
```

如果下载前候选发生变化，停止并重新向用户确认，不要下载另一本书。

用户明确说“下载最匹配的那个”时，可以把这视为对当前第 1 个候选的选择，但仍应先做一次 `--dry-run` 核对。

## 工作流三：额度

用户询问剩余额度时：

```bash
python scripts/zlib_cli.py quota --json
```

只总结账号别名、已用/剩余次数和会员状态。不要展示任何密钥。

## 工作流四：域名故障

搜索出现连接问题时先运行：

```bash
python scripts/zlib_cli.py domains --refresh
```

只使用 `config.json` 中的候选域名。若都不可用，告诉用户检查网络或稍后重试。不要自动关闭 TLS 验证。

## 工作流五：首次配置

如果缺少凭据，Windows 用户优先建议先在 Z-Library 桌面客户端登录自己的账号，然后运行：

```bash
python scripts/zlib_cli.py accounts capture main
```

不要要求用户把 `remix_userkey` 粘贴到聊天里。

如果用户更喜欢环境变量，可提示使用 `ZLIB_USERID` 和 `ZLIB_USERKEY`，但不要让用户在共享终端截图中暴露它们。

## 候选质量判断

更可靠的候选通常具备：

- 书名与用户要求高度一致
- 作者一致
- 用户要求特定版次时，年份/版次信息吻合
- 出版社或译者信息与目标版本一致
- 默认优先 EPUB
- 文件大小不是异常的小文件
- 语言符合用户要求

`score` 是辅助指标，不是事实证明。遇到同名书、合集、教材不同版次、译著不同译本时，要保守处理。

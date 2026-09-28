# Corridor Showtimes（纽约 + 费城艺术影院排片聚合）

[English](README.md) · 在线版：**https://marc506.github.io/corridor-showtimes/**

每天自动抓取 9 家影院的排片，合并成一个网页，按「时间轴 / 列表 / 周」查看。

| 影院 | 数据来源 |
|---|---|
| BAM Rose Cinemas | 官方 JSON API（+ 详情页补导演 / 片长） |
| Film at Lincoln Center | 官网背后的 API |
| Japan Society | WordPress JSON |
| Anthology Film Archives | 网页（按月） |
| Film Forum | 网页（本周 7 天，+ 详情页） |
| Metrograph | 网页（每次只请求一次，站点按 IP 限速） |
| L'Alliance New York | 网页（列表 + 每场详情页） |
| MoMA | 浏览器（Cloudflare），通常回退到 screenslate |
| Philadelphia Film Society | 售票系统 Agile Ticketing 的公开 feed |

设计见 `ARCHITECTURE.md`，每家网站的抓取细节和坑见 `SOURCES.md`，各售票 / 建站平台的读取方式见 `PLATFORMS.md`。

**想看自己关注的影院？** 不需要会编程：把本项目下载到电脑上，让 AI 编程助手帮你加，一般 10–20 分钟。见下面的「自定义影院」。

---

## 自定义影院

在线版只收录作者关注的影院。你可以在自己电脑上做一份，加入任何美国影院：免费，不用写代码。技术部分交给 AI 编程助手，你只需要回答几个问题。

### 需要准备

- 一台电脑（Mac、Windows、Linux 都行），大约 20 分钟。
- 一个**能在你电脑上运行程序的 AI 助手**：[Claude Code](https://claude.com/claude-code)（有桌面版）、[Cursor](https://cursor.com) 或 [Codex](https://openai.com/codex)。只能聊天的助手（比如 ChatGPT 或 Claude 的网页版）做不了这件事：它们没法在你电脑上安装东西，也打不开影院网站。
- 影院的名字，以及影院网站上列出场次的那个网页。

### 步骤

1. **下载本项目。** 打开本项目的 GitHub 页面（<https://github.com/Marc506/corridor-showtimes>），点绿色的 **Code** 按钮，再点 **Download ZIP**。双击下载好的文件解压，会得到一个叫 `corridor-showtimes-main` 的文件夹。（Mac 用户如果以后想让它每天自动更新：把文件夹放到你的个人文件夹里，不要放在「下载」「文稿」「桌面」里。）
2. **在 AI 助手里打开这个文件夹。** Claude Code 桌面版 / Cursor：选「打开文件夹」（Open folder）并选中它。命令行版的助手：先 `cd` 进这个文件夹，再启动助手。
3. **把这句话发给它：**

   > 请阅读这个文件夹里的 AGENTS.md，帮我添加一家影院。

   （`AGENTS.md` 是专门写给 AI 助手看的说明书，里面告诉它每一步该怎么做。）
4. **按它的提问回答**（见下表）。第一次会安装一些东西，需要几分钟。
5. **看结果。** 完成后它会在浏览器里打开网页（`site/index.html`），顶部会出现你的影院按钮。

### AI 助手可能会说什么、你怎么回答

| 它大概会说… | 你这样回答 |
|---|---|
| 「影院叫什么名字？排片页的网址是什么？在哪个城市？」 | 例如：*Nitehawk Williamsburg，https://nitehawkcinema.com/williamsburg/ ，纽约布鲁克林*。网址从浏览器地址栏复制。 |
| 「我可以运行这个命令吗？」/「允许……？」 | 点允许。这些命令只是往这个文件夹里安装 Python 组件、读取影院网站。 |
| 「需要安装一个叫 uv（或 Python）的工具，可以吗？」 | 可以。 |
| 「找到 N 场，最早一场是……」 | 不用做什么，这就是成功了。 |
| 「这家影院的网站格式比较特殊，我来为它写一份读取规则」 | 等几分钟，它在写并且自己测试。 |
| 「这个网站挡住了程序访问（Cloudflare 等）」 | 这家影院没法自动添加，本项目也不会去绕过这类防护。纽约和旧金山的影院有时可以用另一个数据源，助手会主动提出。 |
| 「这个页面上没有找到场次」 | 换成真正列出场次的那个网页（在影院网站上找 Calendar、Showtimes 或 Now Playing）。 |

### 之后

- 所有东西都在**你自己的电脑上**，不会改动在线版网站。
- 场次**不会自己更新**。想更新时对助手说「更新一下排片」，或者让它帮你设成每天自动更新。
- 再加一家，就把同一句话再发一遍。不想看作者的那几家影院：点网页顶部它们的按钮关掉即可（会记住），或者让助手帮你关掉。

### 实在解决不了

[在 GitHub 上提一个 Issue](https://github.com/Marc506/corridor-showtimes/issues/new?template=help-add-cinema.yml)（需要一个免费的 GitHub 账号），写上影院名、排片页网址、用的是哪个 AI 助手、它最后说了什么。这段文字可以让助手帮你写好。

---

## 日常使用

**看排片**：双击 **`~/Applications/Corridor Showtimes.app`**（可拖到 Dock；Spotlight 搜 "Corridor Showtimes" 也能找到）。它打开 `site/index.html`；如果数据超过 13 小时没更新（比如电脑在 1 点 / 13 点都关着），还会在后台触发一次更新，一分钟后刷新网页即可。也可以直接在浏览器收藏 `file:///Users/yanghaolei/cinema/site/index.html`。不需要服务器。

**手机上看**：打开在线版 https://marc506.github.io/corridor-showtimes/ ，Safari 里「分享 → 添加到主屏幕」即可像 App 一样使用。在线版由 Mac 上的定时任务每次抓取后自动发布（`scripts/publish.sh` → `gh-pages` 分支），Mac 关机期间停在最后一次的数据。

重建这个 app（改了图标或路径时）：`/opt/anaconda3/bin/python3 scripts/make_app.py`

- 顶部切换 **时间轴 / 列表 / 周**；`← →` 键换天（周视图换周）。
- 点影院按钮开关某家，悬停出现「只看」。选择会被记住。
- 「只看胶片」= 16mm / 35mm / 70mm（`35mm-to-DCP` 不算）。
- 「非英语（有字幕）」= 已知主要语言不是英语的场次，加上默片 / 无对白片。语言未知的场次会被隐藏，旁边会显示隐藏了多少场。语言来源：影院网站自己写的 > TMDB 查询 > `venues.yaml` 里的 `default_language`（Japan Society = 日语，L'Alliance = 法语）。
- 时间轴里点色块看详情和购票链接；虚线框表示时长未知（按 100 分钟画）。
- 影院按钮上的小圆点：🟡 旧数据（这次抓取失败，显示上次的）· 🔴 从未成功 · 🔵 这次用的是 screenslate 兜底。悬停可看原因。
- 网址里保存了当前状态（日期、视图、筛选），可以收藏或发给别人。

**自动更新**：每天 01:00 和 13:00（纽约时间）后台运行，不会弹出任何东西——唯一的例外是 MoMA 大约每天一次会短暂打开一个 Chromium 窗口（约 30 秒，自动关闭）。Mac 睡眠时错过的那次，唤醒后会补跑；关机则跳过。

**手动更新**：

```bash
./scripts/refresh.sh
```

---

## 安装（新机器 / 重装）

需要 Python 3.12。

```bash
cd ~/cinema
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium   # 只有本机没有对应 Chromium 时才需要
.venv/bin/python -m scraper.run                    # 第一次抓取
open site/index.html
```

安装定时任务（launchd）：

```bash
cp scripts/com.cinema.refresh.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cinema.refresh.plist
```

立刻手动触发一次、查看状态、卸载：

```bash
launchctl kickstart gui/$(id -u)/com.cinema.refresh
launchctl print gui/$(id -u)/com.cinema.refresh | grep -E "state|last exit"
launchctl bootout gui/$(id -u)/com.cinema.refresh
```

> **项目必须放在 `~/Downloads`、`~/Documents`、`~/Desktop` 之外。** macOS 的隐私保护不允许后台任务读这几个文件夹，定时任务会报 `can't open input file`（退出码 127）。项目现在在 `~/cinema`，`~/Downloads/cinema` 只是一个指向它的快捷方式。
>
> plist 里写的是绝对路径 `/Users/yanghaolei/cinema/...`，项目换位置要同步修改 plist 并重新 `bootstrap`。

### 语言数据：TMDB token（可选，但强烈建议）

Metrograph、FLC、Film Forum、MoMA 的网站不写语言，要靠 [TMDB](https://www.themoviedb.org/) 按片名 / 年份 / 导演查原始语言（Letterboxd 的片目就来自 TMDB）。个人非商业使用免费：

1. 注册 themoviedb.org → Settings → API → 申请 Developer key（用途写个人、非商业）。
2. 复制 **API Read Access Token**（很长的一串，v3 的 32 位 API Key 也可以），存进 `config/tmdb_token.txt`（只放这一串）。
3. 下一次运行自动生效。第一次会查几百部片（约 1–2 分钟），结果缓存在 `data/cache/tmdb.json`：查到的永久保存，查不到的 14 天后重试。

日志里每家影院会有一行 `language: site N, tmdb N, default N, unknown N`，可以看覆盖情况。查错了某部片：在 `data/cache/tmdb.json` 里删掉那一条再运行即可。讲座、短片合集、`A + B` 连映这类节目不去查。

---

## 命令行

```bash
.venv/bin/python -m scraper.run                          # 全部影院 + 导出网页数据
.venv/bin/python -m scraper.run --venue metrograph       # 只跑一家（可重复 --venue）
.venv/bin/python -m scraper.run --venue bam --dry-run    # 打印解析结果，不写库
.venv/bin/python -m scraper.run --venue moma --source fallback      # 强制用兜底源（旧写法 screenslate 也行）
.venv/bin/python -m scraper.run --venue moma --source primary       # 只用主源，不兜底
.venv/bin/python -m scraper.run --venue filmforum --parse-fixture tests/fixtures/filmforum/now_playing.html
.venv/bin/python -m scraper.export                       # 只重新生成 site/data.js
.venv/bin/pytest -q                                      # 离线测试（不联网）
```

---

## 新增一家影院

每家影院是 `config/venues.yaml` 里的一条，`source:` 决定怎么读排片：

1. **平台适配器**：网站用的是已知的售票 / 建站系统（Filmbot、Veezi、Agile、The Events Calendar、Squarespace……），只填参数，不写代码；
2. **配方**（recipe）：用一小段 YAML 描述这个网站自己的 HTML（`scraper/recipes/<id>.yaml`）；
3. **自定义模块**：两者都表达不了时才写 Python（`scraper/sources/<id>.py`）。

一般不用自己选，三种加法：

| 方式 | 怎么做 | 结果 |
|---|---|---|
| **AI 助手**（不用写代码） | 在 Claude Code、Cursor 或 Codex 里打开项目文件夹，发送「请阅读这个文件夹里的 AGENTS.md，帮我添加一家影院。」（见上面「自定义影院」） | `AGENTS.md` 带着助手完成安装、运行向导，必要时按任务书写配方 |
| **本地向导** | `python -m scraper.add "Nitehawk Williamsburg" https://nitehawkcinema.com/williamsburg/ --tz America/New_York` | 识别平台、试抓、写入配置和测试，并立刻抓一次，打开 `site/index.html` 就能看到。没有匹配的平台时生成 `handoff/<id>/BRIEF.md`，可以交给任何编程助手；如果你自己设置了 `ANTHROPIC_API_KEY`（可选），则由 Claude 自动写配方 |
| **Claude Code** | 在本仓库里 `/add-venue "影院名" https://…` | 同样的流程，做成了技能（`.claude/skills/add-venue/SKILL.md`） |

向导的结论只有四种：**识别成功**（适配器 + 参数）、**需要配方**、**被拦截**（防火墙或验证码；本项目不做任何绕过——纽约、旧金山的影院仍可以只用 screenslate 兜底）、**这一页没有场次**（多半给的是首页而不是排片页）。

常用命令：

```bash
.venv/bin/python -m scraper.add "影院名" <排片页网址> [--tz America/Los_Angeles] [--region LA] [--lang zh]
.venv/bin/python -m scraper.add ... --json          # 机器可读结果（脚本 / CI 用）
.venv/bin/python -m scraper.add --verify <id>       # 联网抓一次、保存 fixture、跑契约测试
.venv/bin/python -m scraper.repair --venue <id>     # 配方失效时让 Claude 修（需要 API key，每天最多一次）
.venv/bin/pytest tests/test_contract.py -k <id>     # 单家影院的契约测试
```

手写的话：`venues.yaml` 加一条（格式见文件开头的说明和现有条目），`source:` 写 `{adapter: filmbot, base_url: …}` 这样的参数；自定义模块写法见 `handoff/<id>/BRIEF.md` 的第 3 节或 `scraper/sources/japansociety.py`。旧的 v1 写法（`scraper:` / `city:` / `screenslate_nid:`）仍然可以加载。

`venues.yaml` 里的字段：

| 字段 | 作用 |
|---|---|
| `region` | 网页顶部「区域」筛选用的标签（NYC / PHL / LA …）；只有一个区域时不显示那一行 |
| `timezone` | 影院所在时区（默认 `America/New_York`），时间按它显示 |
| `website` | 影院官网，列表视图里影院名链接到这里 |
| `source` | 数据源：`{adapter: <名字>, 参数…}`；`adapter: custom` + `module` 是自定义模块 |
| `fallback` | 主源失败时的兜底源，例如 `{adapter: screenslate, nid: 6}`，也可以是另一个适配器 |
| `horizon_days` | 只保留今天起多少天内的场次 |
| `rate_limit_s` | 同一网站两次请求的最小间隔 |
| `max_requests_per_run` | 每次运行对该站的请求上限（默认 20；适配器和配方遵守） |
| `allow_empty` | 抓到 0 场也算成功（片少的影院） |
| `primary_cooldown_h` | 主源失败后多少小时内直接用兜底（MoMA 用它避免每次都开浏览器） |
| `browser.headless` / `browser.challenge_timeout_s` | 需要浏览器的影院（MoMA） |
| `default_language` | 网站和 TMDB 都没有语言时的默认值 |

screenslate 的 nid 查法：`curl -s 'https://www.screenslate.com/jsonapi/node/venue?filter[title]=<影院名>'`

### 在云端运行（GitHub Actions，可选）

给想把自己那份放在 GitHub 上的人用，默认关闭。开启方法：在仓库 Settings → Secrets and variables → Actions → Variables 里新建变量 `CLOUD_REFRESH`，值为 `true`；Settings → Pages → Source 选 "GitHub Actions"。之后 `.github/workflows/refresh.yml` 每天 UTC 05:00 / 17:00（纽约 1 点 / 13 点）运行：先下载上次发布的 `showtimes.json` 灌回数据库（这样某家失败时仍保留旧数据并标记为旧），再以 `CINEMA_NO_BROWSER=1` 抓取、导出、部署到 Pages。可选的 Secrets：`TMDB_TOKEN`（语言数据）、`ANTHROPIC_API_KEY`（配方失效时自动修复）。作者的在线版由本机 `publish.sh` 发布，不开启它。

云端的限制：数据中心 IP 更容易被限速或拦截——Metrograph 在云端可能只能靠 screenslate 兜底；需要浏览器的影院（MoMA）在云端一律用兜底源。本机运行更稳。

### 数据来源与礼貌抓取

每个适配器只读影院网站或售票系统面向公众发布的页面 / feed：Agile 的 feed 官方要求使用方缓存，我们每天只读两次；Eventive 只使用影院自己的 Eventive 页面随浏览器下发的公开 key，影院要求时移除；其余平台说明见英文 README 的适配器表和 `PLATFORMS.md`。每次运行每家影院只发少量请求（`max_requests_per_run`，默认 20，另有每站间隔），遇到 429 / 403 立即停止，不绕过任何防火墙、挑战页或验证码。网页本身是静态的，不收集访问者信息，偏好只存在浏览器本地。

---

## 常见问题

**网页上某家影院有黄点 / 红点**
悬停看错误。然后看日志：`tail -100 logs/refresh.log`。单独重跑：`.venv/bin/python -m scraper.run --venue <id> --dry-run`。

**某家突然只有很少的场次，或者 0 场**
多半是网站改版。0 场会被判为失败并保留旧数据；条数骤降会在日志里 WARN。原始页面在 `data/raw/<日期>/` 里（保留 14 天），拿它对照 `SOURCES.md` 修解析，并把新页面放进 `tests/fixtures/` 补测试。

**Metrograph 报 429**
按 IP 限速，通常 15 分钟以上才解除。程序已经是每次只请求一次、429 立即停止，不要手动反复重试。当次会自动改用 screenslate。

**MoMA 总是 "via screenslate"**
正常。MoMA 的 Cloudflare 挡住了自动浏览器；程序大约每天试一次，失败就用 screenslate（对 MoMA 覆盖完整）。不做绕过验证之类的处理。想完全不弹窗口：把 `venues.yaml` 里 MoMA 的 `primary_cooldown_h` 改成很大的数（如 `100000`），它就一直直接用 screenslate。

**screenslate 403**
它的防火墙拒绝 Python 的 TLS 握手，所以这个源通过系统自带的 `curl` 请求（`transport = "curl"`）。如果 curl 也 403，说明对方改了策略，只能等或换源。

**Philadelphia Film Society**
`filmadelphia.org` 整站被防火墙拦截（浏览器也会被判为机器人），所以改用它的售票系统 Agile Ticketing 公开的 JSON feed（官方提供，每 10 分钟更新）。如果哪天 feed 返回空或 404，可能是 GUID 换了：搜索 `prod5.agileticketing.net entrypoint.aspx "Philadelphia Film Society - EVENTS"` 找新的 GUID，填到 `venues.yaml` 的 `agile_guid`（或改用 `source: {adapter: agile, guid: …, host: prod5.agileticketing.net}`）。

**定时任务没跑**
`launchctl print gui/$(id -u)/com.cinema.refresh | grep -E "state|last exit"`；退出码 127 = 路径或权限问题（见上面的文件夹说明）。launchd 自己的输出在 `logs/launchd.err.log`。

**Playwright 报要 `playwright install`**
`pyproject.toml` 把 Playwright 锁在 1.62.0，对应本机已有的 Chromium。换机器时运行一次 `.venv/bin/python -m playwright install chromium`。

---

## 目录

```
config/venues.yaml        影院注册表（config/venues.schema.json 校验）
scraper/                  抓取、存储、导出
scraper/adapters/         平台适配器 + 配方解释器（recipe.py）
scraper/recipes/          配方文件
scraper/sources/          自定义模块（每家一个文件）
scraper/add.py detect.py  加影院向导与平台探测
templates/BRIEF.md.j2     交给 AI 助手的任务书模板
AGENTS.md CLAUDE.md       写给 AI 助手的说明（加影院的固定流程 + 开发规则）
.github/                  可选的云端定时抓取工作流、加影院求助的 Issue 模板
site/                     网页（index.html / app.js / styles.css；data.js 是生成物）
data/                     showtimes.sqlite、showtimes.json、raw/ 原始快照、cache/ 详情页缓存、browser_profile/
scripts/refresh.sh        定时任务调用的脚本
scripts/com.cinema.refresh.plist   launchd 配置
logs/refresh.log          运行日志
tests/                    离线解析测试 + fixtures
```

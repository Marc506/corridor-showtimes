# Corridor Showtimes — 架构

艺术 / 重映影院的排片聚合器：每天抓取两次，合并成统一数据，以时间轴 / 列表 / 周三种视图展示，并发布到 GitHub Pages。公开实例覆盖波士顿、纽约、费城二十一家影院；任何人 fork 后给出「影院名 + 网址」就能加入自己的影院。每家影院网站的抓取细节见 [`SOURCES.md`](SOURCES.md)，各类平台（售票系统 / 建站系统）的读取方式见 [`PLATFORMS.md`](PLATFORMS.md)。

**目标**：不懂编程的人给出「影院名 + 网址」，就能把一家美国影院加进自己的排片日历。程序按网站所用的系统自动工作；做不到的，给出一份可以直接交给 AI Agent 的任务包，或者明确说「这家做不了、为什么」。
**非目标**：托管服务（网页里直接加影院需要常驻服务器与运营方代付 LLM 费用，本项目不承担；每人在自己电脑上一份）；绕过任何反爬 / 验证码；美国以外的影院（时区是按影院配置的，留了口子）。

## 1. 核心设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12（httpx、BeautifulSoup/lxml、Playwright） | 抓取生态最成熟 |
| 前端 | 纯静态 HTML + 原生 JS，无框架、无构建步骤 | 易于修改；可直接部署为静态站点 |
| 数据流 | 抓取 → SQLite → 导出 `site/data.js` | 用 `<script src="data.js">` 注入全局变量，网页从 `file://` 打开也能用（`fetch` 在 file:// 下不可用） |
| 调度 | 每个拷贝都在自己的电脑上每天 01:00 / 13:00 自动更新：`python -m scraper.schedule on` 按系统生成 launchd / 任务计划程序 / systemd（或 cron）任务；加影院流程默认开启。另有可选的 GitHub Actions 工作流（默认关闭） | 01:00 避开影院自己的午夜发布，13:00 赶上白天更新的下周排片 |
| 抓取位置 | 本机，而非云端 | Metrograph 对数据中心 IP 限速更严、需要浏览器的站在云端没有浏览器；也不需要任何人维护服务器或付费 |
| 时区 | 存 ISO 8601 带偏移；每家影院有自己的 `timezone`（默认 `America/New_York`） | 美国其他城市的影院时间才不会错 |
| 失败策略 | 每家影院独立；失败时保留上次成功的数据并标记 stale | 旧数据加提示，好过一片空白 |
| 兜底源 | screenslate.com 开放的 JSON:API | 主源失败时自动替换，并在界面上标注 |
| 可扩展性 | 三层数据源：平台适配器（只填参数）→ 声明式配方（YAML）→ 自定义模块（Python） | 实测 28 家美国艺术影院里平台适配器零代码覆盖约 40%，配方再覆盖约 35%，其余纯 JS 或被防火墙挡；三层缺一不可，配方层是重点 |
| 加影院 | 用户在自己电脑上交给 AI 编程助手（`AGENTS.md` 规定流程），助手调用 `scraper.add` 向导：探测平台 → 试抓 → 写入配置 + fixture；做不到时按 Agent 任务包写配方 | 零服务器、零代付；用户不需要知道影院用的是什么系统，也不需要会编程 |

## 2. 目录结构

```
├── config/venues.yaml          影院注册表（§4）；venues.schema.json 是它的 JSON Schema
├── scraper/
│   ├── models.py               Screening / VenueStatus / VenueConfig / RawPage
│   ├── config.py               读取 venues.yaml（v1 / v2）、Schema 校验、面向外行的错误信息
│   ├── registry.py             按 source.adapter 装配抓取器；@register("<module>") 注册自定义模块
│   ├── base.py                 BaseScraper、HTTP 客户端（httpx / curl）、Playwright 浏览器会话、详情页缓存、请求预算
│   ├── adapters/               平台适配器（filmbot、veezi、agile、tribe、squarespace、ics、alamo、wp_my_calendar、
│   │                           eventive、spektrix、boxofficeapi、wix、jsonld、screenslate）与配方解释器 recipe.py；@register_adapter 注册
│   ├── recipes/<id>.yaml       配方文件；recipe.schema.json 是配方的 JSON Schema
│   ├── sources/                自定义模块，每家一个文件（filmadelphia.py 是 agile 适配器的薄壳）
│   ├── probe.py                SiteProbe：对一个网站的有限、礼貌的探测（§5.7）
│   ├── detect.py               探测流程：候选 → 试抓 → 结论（§5.7）
│   ├── add.py                  加影院向导（交互 / --json / --verify）
│   ├── recipe_gen.py repair.py 用 Claude 生成 / 修复配方（可选）
│   ├── handoff.py              Agent 任务包（templates/BRIEF.md.j2）
│   ├── contract.py             Screening 契约检查（测试与 --verify 共用）
│   ├── normalize.py            时间 / 时区、标题大小写、语言文字解析、稳定 id
│   ├── language.py             语言补全：影院文本 → TMDB → 默认值（§5.5）
│   ├── i18n.py                 面向用户的中英文消息
│   ├── store.py                SQLite 读写；seed_from_export 供无状态 CI 回灌
│   ├── export.py               SQLite → data/showtimes.json + site/data.js
│   └── run.py                  命令行入口：抓取、校验、兜底、冷却、写库、导出
├── site/                       index.html / app.js / calendar.js（.ics 生成）/ styles.css / 图标与 manifest（data.js 为生成物）
├── templates/BRIEF.md.j2       Agent 任务书模板
├── handoff/<id>/               （不入库）向导生成的任务包
├── AGENTS.md                   写给 AI 助手的说明：帮非技术用户加影院的固定流程 + 开发规则
├── CLAUDE.md, .claude/skills/add-venue/   Claude Code 读取 AGENTS.md；/add-venue 技能
├── .github/                    refresh.yml（可选的云端定时抓取 + Pages，默认关闭）、ISSUE_TEMPLATE（加影院求助）
├── scripts/
│   ├── refresh.sh              作者机器上旧定时任务的入口，等同 `python -m scraper.update --publish`
│   ├── publish.sh              把 site/ 推到 gh-pages 分支
│   ├── open_site.sh / make_app.py  本机双击打开的 macOS 小程序
├── tests/                      离线测试 + 真实页面 fixtures（tests/fixtures/platforms/ 是各平台样本）
├── data/                       （不入库）SQLite、原始快照、详情页缓存、浏览器 profile、TMDB 缓存
└── logs/                       （不入库）运行日志
```

## 3. 数据模型

### 3.1 `Screening`：一场放映（一个影院 × 一个开始时间 × 一个节目）

| 字段 | 说明 |
|---|---|
| `id` | `sha1(venue_id|start|规范化标题)[:16]`，跨次抓取稳定；同一时间同一部片在两个影厅（`screen` 不同）时，影厅名排在后面的那场的 id 另算入影厅名，两场都保留（`base.dedupe`） |
| `venue_id` | venues.yaml 里的 key |
| `title` | 展示用标题；全大写来源（Film Forum、Anthology、PFS）统一转换大小写 |
| `start` / `end` | ISO 8601，带影院所在时区的偏移；`end` 来自影院或 start + 片长，没有则为空 |
| `day` | 影院本地日期（= `start[:10]`），前端按天索引 |
| `director` / `year` / `runtime_min` | 可选 |
| `format` | `35mm` / `16mm` / `70mm` / `DCP` / `Film`（胶片但规格未知）等 |
| `language` | `"Japanese"`、`"French, Wolof"`、`"Silent"`、`"Opera (subtitled)"`；空 = 未知 |
| `series` / `screen` / `note` | 影展或系列、影厅、备注（"Q&A with…"、"Sold out"） |
| `detail_url` / `ticket_url` | 影院自己的影片页和购票页 |
| `imdb_id` | 影院公布了 IMDb 号时填（`tt0090605`）：TMDB 按它精确匹配，不按片名猜 |
| `source` | `primary`，或兜底适配器的名字（通常是 `screenslate`） |

多片连映、短片合集算一条，标题用 ` + ` 连接（片数多时写成 "A + B + N more"）。

### 3.2 `VenueStatus`：每家影院每次运行的健康状态

`status`（`ok` / `stale` / `failed` / `disabled`）、`fetched_at`（最后一次成功）、`count`、`horizon_end`（数据覆盖到哪天）、`error`、`source`（本次实际用的源）、`primary_failed_at`（主源最近一次失败时间，用于冷却）。

### 3.3 SQLite

`screenings` 表存上面的字段，另加 `first_seen` / `last_seen`；`venue_status` 表存状态。写入规则：

* **某影院抓取成功**：在一个事务里删除该影院今天及以后的旧行，写入新行，过去的行保留作历史。
* **抓取失败**：不动放映数据，只把状态改成 `stale`（有旧数据时）或 `failed`，并记录错误。
* 新增字段通过启动时的轻量迁移（`ALTER TABLE ADD COLUMN`）加入。

## 4. 影院注册表 `config/venues.yaml`

```yaml
version: 2
venues:
  - id: nitehawk
    name: Nitehawk Williamsburg
    short: NH                        # 顶部按钮上的缩写
    region: NYC                      # 前端「区域」筛选
    timezone: America/New_York       # 默认 America/New_York
    color: "#ff6b6b"
    website: https://nitehawkcinema.com/williamsburg/
    source:                          # 数据源：适配器名 + 参数
      adapter: filmbot
      base_url: https://nitehawkcinema.com/williamsburg
    fallback: {adapter: screenslate, nid: 6}   # 可选；也可以是另一个适配器
    location:                        # 「加入日历」的地址；geo 可选（[纬度, 经度]，Apple 日历据此显示地图）
      address: "136 Metropolitan Ave, Brooklyn, NY 11249"
      geo: [40.71609, -73.9625]
      # places: [{match: <影厅名片段>, name, address, geo}]  影院分几栋楼时按场次的 screen 选地址
    horizon_days: 45                 # 只保留今天起多少天
    rate_limit_s: 2                  # 同一域名两次请求的最小间隔
    max_requests_per_run: 20         # 每次运行对该站的请求上限（适配器和配方遵守）
    # 可选：enabled, allow_empty, default_language, primary_cooldown_h, browser.{headless, challenge_timeout_s}

  - id: metrograph
    source: {adapter: custom, module: metrograph}     # scraper/sources/metrograph.py
```

* **兼容 v1**：没有 `version`、顶层是列表的旧文件照样加载；每条在内存里转换成 `source: {adapter: custom, module: <scraper>}`、`fallback: {adapter: screenslate, nid: <screenslate_nid>}`、`region: <city>`。`VenueConfig` 保留 `scraper` / `screenslate_nid` / `city` 作为别名，`extra` 继续兜住未知字段。
* **校验**：`config/venues.schema.json`（JSON Schema）加语义检查（id 重复、时区名无效、适配器不存在、适配器缺必填参数、自定义模块文件不存在）。错误是一句一行的人话——「第 3 家影院（c）缺少 name」——不出现校验器的堆栈；语言跟随 `--lang` / `CINEMA_LANG` / `LANG`。

公开实例的二十一家：

| 影院 | 数据源 |
|---|---|
| BAM Rose Cinemas | custom：JSON API + 详情页补全 |
| Film at Lincoln Center | custom：官网背后的 JSON API |
| Japan Society | custom：WordPress 自定义端点 |
| Anthology Film Archives | custom：服务端 HTML，按月（另有等价配方作解释器回归测试） |
| Film Forum | custom：服务端 HTML，7 天 + 详情页补全（时间无上午 / 下午，配方表达不了） |
| Metrograph | custom：服务端 HTML，单页（每次运行只请求一次） |
| L'Alliance New York | custom：列表卡片 + 每场详情页（配方表达不了） |
| MoMA | custom：Playwright 浏览器；通常回退到 screenslate |
| Philadelphia Film Society | custom `filmadelphia`：`agile` 适配器的薄壳，固定 PFS 的 GUID 与集群 |
| Landmark Ritz Five | `boxofficeapi`：Webedia 平台的公开排片接口 |
| Lightbox Film Center | `wix`：Wix Events 页面内嵌的 JSON |
| Coolidge Corner Theatre | `recipe`：每日排片页（`/showtimes?date=`），三周 |
| Brattle Theatre | `filmbot`：平台适配器，只填 `base_url` |
| Harvard Film Archive | `recipe`：日历页（`?page=2`、`?page=3`），每场带 `time[datetime]` |
| MFA Boston | `recipe`：电影节目页，一卡一场 |
| ICA Boston | `recipe`：电影日历页（场次很少，`allow_empty`） |
| Somerville Theatre | custom `tapos`：网站排片页背后的 TAPOS XML，一次请求；IMDb 号交给 TMDB 精确匹配 |
| Bryn Mawr Film Institute | custom `brynmawr`：本周页 + 之后场次的影片页（时间无上午 / 下午，配方表达不了） |
| Hiway Theater、County Theater、Ambler Theater | custom `renew`（参数 `base_url`）：Renew Theaters 模板的首页 + 特别放映页（同样没有上午 / 下午） |

## 5. 抓取层

### 5.1 `BaseScraper` 与适配器注册表

```python
class BaseScraper:
    needs_browser = False       # True：通过共享的 Playwright 会话取页面
    transport = "httpx"         # "curl"：对拒绝 Python TLS 的站点（screenslate）
    PARAMS = {}                 # 适配器：venues.yaml source: 里必填的参数（加载时校验）
    DETECT_ORDER = 100          # 适配器：探测顺序，越小越先
    # self.venue、self.tz（venue.timezone）、self.params（source 里除 adapter 外的键）
    def fetch(self) -> list[RawPage]            # 只做网络 IO
    def parse(self, pages) -> list[Screening]   # 纯函数，离线可测
    def enrich(self, screenings) -> None        # 可选：详情页补字段，失败不致命
    def run(self) -> (screenings, VenueStatus)  # fetch → 保存原始快照 → parse → enrich
    @classmethod
    def detect(cls, probe) -> Candidate | None  # 适配器：从 SiteProbe 看出「这是我的平台」
```

* `build_scraper(venue)` 按 `source.adapter` 找类：`scraper/adapters/<name>.py` 里 `@register_adapter("<name>")` 的类；`custom` 则是 `scraper/sources/<module>.py` 里 `@register("<module>")` 的类。`build_fallback(venue)` 对 `fallback` 做同样的事。
* **请求预算**：适配器与配方每次运行的请求数不超过 `max_requests_per_run`（默认 20），超出抛 `RequestBudgetExceeded`；翻页类适配器遇到预算用完就停止翻页、用已抓到的页。自定义模块与 screenslate（按天请求、自有节奏）不受此限。
* 需要月份 / 年份推断的解析器以页面的抓取日期（影院本地）为基准，保证测试结果不随运行日期变化；`normalize.nearest_date` 是通用的「无年份日期 → 离抓取日最近且偏向未来」。

`fetch` 与 `parse` 严格分离：测试直接用 `tests/fixtures` 里的真实页面调用 `parse`，不联网。
需要月份 / 年份推断的解析器（Film Forum、MoMA）以页面的抓取日期为基准，保证测试结果不随运行日期变化。

### 5.2 HTTP 客户端

* **请求头与重试**：固定桌面 Chrome UA，超时 30s；遇到 5xx / 网络错误时指数退避，最多重试 3 次。
* **429 立即停止**：该影院本次不再请求。
* **限速**：同一域名两次请求之间按 `rate_limit_s` 间隔。
* **原始快照**：每个响应原文写入 `data/raw/<date>/<venue>[_n].<ext>`，保留 14 天，便于回溯解析问题。
* **详情页缓存**：原始 HTML 缓存在 `data/cache/<venue>/`，7 天有效。缓存的是原文而不是解析结果，所以解析器修复后对缓存立即生效。

### 5.3 浏览器路径（MoMA、`render: browser` 的配方）

* **会话**：共享 Chromium 会话，profile 持久化在 `data/browser_profile/`，Cloudflare 的 clearance cookie 可以复用。
* **判定失败**：页面停在挑战页超过 `challenge_timeout_s` 即算失败。浏览器被关闭、崩溃、超时一律转成一行错误信息，不打印堆栈。
* **不绕过**：不做任何绕过防护的处理，失败即走兜底。
* **`CINEMA_NO_BROWSER=1`**（CI 里设置）：需要浏览器的抓取直接失败（`BrowserDisabled`），影院干净地走兜底或标为旧数据。

### 5.4 兜底与冷却（`run.py`）

```
for venue in enabled venues:
    if 主源在冷却期内:            跳过主源
    else:                        result = primary.run(); validate(result)
    if 失败 and venue.fallback:
        result = build_fallback(venue).run()          # source = fallback.adapter（通常 "screenslate"）
    fill_languages(result)
    store.apply(result)
```

* **校验**：
  * 解析出 0 条视为失败，配置了 `allow_empty` 的影院除外。
  * 条数比上次骤降 70% 以上时写入，但打 WARN。
  * 超出有效时间窗的行丢弃；过去日期静默丢弃，太远的未来打 WARN。
* **冷却（`primary_cooldown_h`）**：主源失败后的一段时间内直接用兜底，避免反复请求刚封禁过我们的网站（Metrograph），也避免每次运行都开浏览器（MoMA）。
* **兜底**：`fallback` 可以是任何适配器（例如主源 `recipe` 抓官网、兜底 `veezi` 抓售票页）；兜底来的行和状态都记下兜底适配器的名字，前端显示「via <名字>」。
* **今天**按影院时区取：校验窗口、「成功时替换今天及以后的行」都按影院本地日期。
* **运行锁**：`data/.run.lock`（`flock`）保证同一时间只有一个写库的运行。手动运行和定时任务互不冲突。

### 5.5 语言补全（`language.py`）

为「有字幕（非英语片、默片、开放字幕场次）」筛选服务。优先级：

1. **影院网站自己的文字**："In French and Wolof with English subtitles"、"silent"、PFS feed 的 Original Language。
2. **歌剧 / 芭蕾直播**（按系列名或备注识别）：直接标为 `Opera (subtitled)`，不查 TMDB，免得配到同名电影。
3. **TMDB 查询**（需 `config/tmdb_token.txt`）。影院给了 IMDb 号（`imdb_id`）时直接 `/find/{imdb_id}`，一定是这部片；否则按片名查，宁可「未知」，不要配错：
   * 先清理片名：去掉 "EC: "、"X Presents: "、"w/ Q&A"、"(4K Restoration)"，以及冠词前的「导演名's」。
   * 讲座、短片合集、连映不查。
   * 有年份时要求 ±1 年内，同年优先；仍有多个候选时用导演核对。
   * 没有年份时，先借用其他影院同名片的年份和导演；再优先当年的新片；所有候选语言相同时直接采用；有一部热度是第二名 3 倍以上时取它；都不满足就放弃。
   * 结果缓存在 `data/cache/tmdb.json`：命中的永久保存，未命中的 14 天后重试。
4. **影院默认语言**（`default_language`：Japan Society = 日语，L'Alliance = 法语）。

**导演和片长补全**（同一次 TMDB 查询）：只有匹配「确定是这部片」时才用（年份对上、导演核对过、今年唯一的新片或热度明显领先的唯一一部）；只是「所有候选语言相同」的匹配只填语言，不填导演。影院网站写了的导演从不覆盖；缺年份时顺带补上 TMDB 的年份，但不填晚于今年的上映年份。导演和片长用一次 `/movie/{id}?append_to_response=credits` 请求取得（TMDB 的片长 0 表示未知，忽略），和匹配结果一起缓存在 `data/cache/tmdb.json`；补上片长时同时算出结束时间。影院写了的片长不覆盖。

**从 screenslate 补导演**（`scraper/crossref.py`，只对 `fallback` 是 screenslate 的影院）：TMDB 之后仍缺导演的主源场次（FLC 的数据没有导演；多片节目 TMDB 查不到），去 screenslate 找同一场。条件是同一影院、开场时间相差不超过 10 分钟、片名相似：取较短片名的词重合比例，同一时间只有一场时要求 ≥ 0.34，多场时要求 ≥ 0.6，打平就放弃。找到后复制导演（按逗号拆开去重，超过 4 人显示前 3 人加「…」），缺的话顺带补片长、单片年份和格式；影院写了的不覆盖。补上导演的场次再交给 TMDB 核对一次，以补片长和语言。只请求有这类场次的日期，节目详情只查时间相近的；响应缓存 12 小时（`data/cache/screenslate/`）。

### 5.6 命令行

```
python -m scraper.run                                   # 全部影院 + 导出
python -m scraper.run --venue metrograph --dry-run      # 只打印解析结果
python -m scraper.run --venue moma --source fallback    # 强制兜底（旧名 screenslate 同义）；--source primary 关闭兜底
python -m scraper.run --venue filmforum --parse-fixture tests/fixtures/filmforum/now_playing.html
python -m scraper.export                                # 只重新导出
python -m scraper.add "Name" <url> [--tz …] [--region …] [--json]   # 加影院向导（§5.7）
python -m scraper.add --verify <id>                     # 联网抓一次 → 存 fixture → 契约检查
python -m scraper.repair --venue <id> | --failed        # 用 Claude 修复失效的配方（可选）
python -m scraper.store --seed <showtimes.json 路径或 URL>   # 从上次发布的导出回灌（CI）
```

### 5.7 平台适配器、配方与加影院向导

**数据源三层**：

1. **平台适配器**（`scraper/adapters/`，零代码，参数见 `PLATFORMS.md`）：

   | adapter | 参数 | 探测签名 |
   |---|---|---|
   | `filmbot` | `base_url`（`endpoint: posts` 读 WP 文章形态） | 页面含 `filmbot` / `nj/v1`，且 `<base>/wp-json/nj/v1/showtime/listings` 返回 JSON |
   | `alamo` | `market`、`cinema_id?` | 域名 `drafthouse.com`；`/theater/<slug>` 定位门店 |
   | `veezi` | `site_token`、`region` | 正则 `siteToken=([a-z0-9]{26})`；优先读售票页的 JSON‑LD，HTML 补导演 / 年份 / 规格与售罄 |
   | `agile` | `guid`、`host` | Agile 链接里的 `epguid=`（节目列表入口优先）→ 依次试站点链到的 host 与 prod1–6，只认 JSON |
   | `tribe` | `base_url`、`categories?` | The Events Calendar 标记 + `/wp-json/tribe/events/v1/events` 返回带 `events` 的 JSON |
   | `wp-my-calendar` | `base_url` | `my-calendar` 标记 + `/wp-json/my-calendar/v1/events` |
   | `squarespace` | `base_url`、`collection` | `Static.SQUARESPACE_CONTEXT`；链接 / sitemap 里的候选路径 `?format=json` 的 `typeName == events` |
   | `eventive` | `bucket`、`api_key`、`site` | `*.eventive.org` → tenant bundle 里的 `event_bucket` / `api_key`（仅限影院公开页面里的 key） |
   | `spektrix` | `client` | `system.spektrix.com/<client>/` |
   | `ics` | `url`、`categories?` | `text/calendar` 链接、`.ics` / `webcal://` / `?ical=1` |
   | `wix` | `pages` | 页面含 `wix-warmup-data` 且带 Events 记录；在首页链接里挑未开场场次最多的 `/events*` 页 |
   | `jsonld` | `pages`、`follow?` | 页面里 `startDate` 带时间的 `Event` / `ScreeningEvent`（Film Forum 首页那种空日期不算） |
   | `screenslate` | `nid` | 不参与探测，只作兜底 |

2. **配方**（`adapter: recipe`，`source.recipe: <id>` 指 `scraper/recipes/<id>.yaml`，或内联）：声明式描述「抓哪些页、日期从哪来、哪个节点是一个节目、每个字段怎么读」。解释器 `scraper/adapters/recipe.py` 只实现这些原语，不做通用模板语言：
   * 页面：URL 模板（`{year}` `{month}` `{day}` `{date:%-m/%-d/%Y}`），`paging: none | monthly {months} | daily {days}`，`render: html | browser`，`stop_when_empty`。解析时从页面 URL 反推该页代表的年月日（模板转正则），所以 `parse()` 仍是页面的纯函数。
   * 日期四形态（`PLATFORMS.md` §11）：`heading`（日期标题与条目按文档顺序交错）、`attr`（条目自带日期，可带时间）、`container`（每天一个容器）、`page`（一页一天，日期来自 URL）。缺年 / 缺月时取页面 URL 的，否则按「离抓取日最近且偏向未来」推断。
   * 字段：`selector` / `text_after`（某节点之后的裸文本行）/ `per_time`（在每个时间节点上取，如每场的锚点或购票链接），`attr`、`regex`（命名组直接映射到字段，`meta` 伪字段只用命名组）、`strip_prefix`、`template`（`{page_url}#{value}`）、`case: smart`、`parse: language`。时间默认覆盖 `7:00pm` / `7:00 PM` / `7 PM` / `19:00`。
   * 明确不支持：Film Forum 的无上午 / 下午、L'Alliance 的「列表 + 每卡详情页」——留在 custom。
   * 回归：Anthology、Metrograph 各有一份配方，与自定义解析器在同一 fixture 上比对——Anthology 全字段一致，Metrograph 除 `note` 外一致（按日期拆分的影片描述备注与售罄样式是自定义逻辑）。

3. **自定义模块**（`adapter: custom`）：配方表达不了的站。

**为什么是配方而不是每次运行让 LLM 抽取**：每次调用 LLM 的成本随影院数线性增长、结果不可复现、无法离线测试；配方是数据，可以由 LLM 一次生成、由人或 Agent 修改、离线验证、失效时再修一次。

**探测**（`scraper/probe.py` + `scraper/detect.py`）：

1. `SiteProbe` 抓用户给的 URL 与首页；记录状态码、`Content-Type`、是否挑战页（Cloudflare / Sucuri / Incapsula / 其他 WAF 的签名）、可见文本里的时间 token 数、外链、JSON‑LD、WordPress REST 根。**总请求数上限 12，同一域名间隔 2 秒，不重试**；某个域名一旦返回 403 / 429 / 挑战页，就不再请求它。
2. 按 `DETECT_ORDER` 调用各适配器的 `detect()`，得到候选（适配器 + 参数 + 证据）。一个都没有且页面上没有时间时，再试常见排片路径（`/calendar` `/showtimes` `/now-playing` `/films` `/schedule` `/events`）后重跑一遍。
3. **试抓**：每个候选真的 `fetch` + `parse` + `validate()` 一次，取「未来场次最多」的，平手取 `DETECT_ORDER` 小的。
4. 都不行：HTML 里有时间 → 配方路径（有 API key 则由 Claude 生成并验证，否则 `needs_agent`）；HTML 里没有但浏览器渲染后有 → `needs_agent`（`render: browser` 的配方）；被挑战页挡住 → `blocked`；都没有 → `no_showtimes`（多半给的是首页，或网址打不开）。
5. 时区从网页上的地址（JSON‑LD `addressRegion`、「City, ST 12345」、州名）推断，州 → 时区表；`--tz` 优先，推不出时交互模式会问，非交互默认纽约并提示。

**向导** `python -m scraper.add`（`scraper/add.py`）：规范化输入（id 由名字生成 ASCII slug 并去重，颜色从调色板自动分配）→ 探测 → 成功时追加 `venues.yaml` 条目（保留文件原有内容与注释）、把试抓页存进 `tests/fixtures/<id>/`（带 `fixture.yaml` 清单，标记 `generated_by: scraper.add`）、写薄壳测试 `tests/test_<id>.py`，交互模式下再跑一次 `scraper.run --venue <id>`；需要 Agent 时写 `handoff/<id>/`；被拦截 / 没有场次时给人话结论与下一步。每一步一句话说明进度；`--json` 输出 `{status: ok|needs_agent|blocked|no_showtimes, reason, adapter, source, evidence, summary, sample, next_steps, files, handoff, brief}`。`--verify <id>` 联网抓一次 → 保存 fixture（只覆盖向导生成的 fixture，手工维护的只检查）→ 契约检查 → 打印「解析出 37 场，最早 9/29 7:00pm《…》，最晚 10/19」。

**用 Claude 生成 / 修复配方**（可选，`scraper/recipe_gen.py`，key 来自 `ANTHROPIC_API_KEY` 或 `config/anthropic_key.txt`）：输入是去掉 `<script>`/`<style>`、截到约 60K 字符的页面，加配方 Schema、`PLATFORMS.md` §11 的日期形态说明和一份真实配方；模型 `claude-opus-5-5`（Claude Opus 5.5），结构化输出（`output_config.format`）直接得到 `{recipe_yaml, notes}`，开启服务端拒答回退（`fallbacks: "default"`）。解释器在同一页面上运行配方并判定——≥ 1 条未来场次、≥ 80% 的条目节点解析出时间、日期落在合理窗口——不通过就把「解析出 N 条、样例 3 条、问题」回灌给模型，最多 3 轮。`python -m scraper.repair --venue <id>` 用最新页面（抓不到就用当天的原始快照）走同一流程修复失效配方，每家每天最多一次；`refresh.sh` 设 `AUTO_REPAIR=1` 时对失败的配方影院自动执行，CI 在配置了 key 时也会执行。

**Agent 任务包**（没有 key、三轮失败、或配方表达不了）：`handoff/<id>/` 里有 `BRIEF.md`（`templates/BRIEF.md.j2` 生成，自包含：目标与影院信息、`Screening` 字段契约、首选配方路径（Schema + 两份真实配方）、次选 Python 路径（`BaseScraper` 接口 + `japansociety.py` 全文）、验收命令、禁止事项、完成后删除任务包）、`detect.json`（探测证据）、`pages/*.html`（含浏览器渲染版）、`venue.yaml`（条目草稿）。仓库根的 `CLAUDE.md` 与 `.claude/skills/add-venue/SKILL.md` 让 Claude Code 用户 `/add-venue "Name" URL` 一条命令走完「跑向导 → 按任务书写配方 → 验证」；用别的 Agent 的人复制 `BRIEF.md`。

**契约**（`scraper/contract.py`，`tests/test_contract.py` 与 `--verify` 共用）：对有 `fixture.yaml` 的每家影院（以及 `tests/fixtures/platforms/venues.yaml` 里覆盖每个适配器的示例影院）运行 `parse()`，断言：至少 1 条；两次解析 id 相同；标题非空；`start` 带偏移且与影院时区在该日期一致；`day == start[:10]`；`end` 晚于 `start`；链接为绝对 URL；片长 1–600；年份 1888–明年；抓取日前 1 天之后的场次里 ≥ 90% 落在 `horizon_days + 60` 天内（预售的歌剧直播等可以更远），且没有早于抓取日 62 天以上的（月视图页面包含本月已过去的日子）。

## 6. 导出格式 `site/data.js`

```js
window.CINEMA_DATA = {
  generated_at: "2026-09-28T05:08:56Z",
  venues: [ { id, name, short, color, region, city, timezone, website, adapter, location,
              status, fetched_at, count, horizon_end, error, source } ],
  screenings: [ { ...Screening（不含 scraped_at） } ],   // 只导出昨天及以后
  days: { "2026-09-28": [screening_id, ...], ... }     // 按天索引（影院本地日期）
};
```

同时写 `data/showtimes.json`（同结构的纯 JSON）；CI 把它一起发布到 Pages，下次运行用 `store.seed_from_export()` 灌回。`city` 是 `region` 的旧名；`adapter` 为自定义模块时为空（前端提示「数据来自影院的 X 系统」）。几十家影院内 `data.js` 仍是单文件；超过约 100 家时应按区域拆文件（见 §10）。

## 7. 前端 `site/`

单页、无框架、无构建。所有 DOM 由 `app.js` 里的几个 `render*` 函数从 `window.CINEMA_DATA` 与一个 `state` 对象派生。

* **视图**：
  * 时间轴（默认）：每家影院一行，重叠的场次用贪心算法分道（lane packing）；块宽 = 片长，片长未知时按 100 分钟画成虚线框。点击出详情弹窗。
  * 列表：按影院分组，同一节目的多个场次合为一行。影厅 / 场地名不在网页上显示（不同影厅的同一节目也合为一行），只写进「加入日历」的事件（地点与备注）。同一部片在同一时间于两个影厅开映时，只显示一个时间并标「×2」，鼠标悬停（手机上点按）弹出每个影厅一个框，各自链接到自己的购票页；搜索结果同样处理；时间轴里是两个色块，详情弹窗只在这种情况下注明影厅。
  * 周：7 列，从周四开始，也可从今天开始。点片名跳到当天时间轴并高亮。
* **区域**：顶部一行区域按钮（NYC / PHL / BOS …），多选，记在 `localStorage` 与 URL `r=`；未选区域的影院按钮熄灭。打开一个区域（点按钮或「只看」）时，这个区域的影院全部点亮，包括之前单独关掉的；其他区域的影院保留各自的开关，重新打开那个区域时再全部点亮。关掉最后一个区域就是全部熄灭（URL `r=` 为空、`localStorage` 存空列表），页面提示「没有选中任何影院」并给出「全选」。只有一个区域时隐藏这一行。
* **筛选**：影院多选、只看胶片、有字幕（非英语片、默片、开放字幕场次）、隐藏已开场、片名 / 导演搜索。「非英语」筛选会显示因语言未知而隐藏的场次数。
* **状态**：放在 URL hash（`#/2026-10-03?view=list&v=bam,filmlinc&sub=1`），刷新和分享都保留。影院选择另存 `localStorage`；新加入的影院自动选中。
* **默认今天**：看今天时 URL 里不写日期（`#/?view=list`），所以收藏、主屏幕启动、恢复的标签页都从今天开始；URL 里已经过去的日期在打开时改为今天，未来的日期保留。页面一直开着时，原本在看「今天」的会在跨过午夜或从后台切回时翻到新的一天；在后台超过一小时再切回会重新加载，拿到最新数据。
* **搜索**：搜索框有内容时离开当天 / 当周视图，列出从今天起所有匹配片名、导演或系列的场次，按日期分组；影院、区域和其他筛选照常生效，影院按钮上的数字变成命中数，日期导航隐藏。清空搜索框或按 Esc 回到原视图；搜索词写进 URL（`?q=godard`），可以分享。
* **加入日历**（`site/calendar.js`，纯函数，测试里用 Node 直接加载）：详情弹窗里的按钮在浏览器里生成 RFC 5545 的 .ics（`DTSTART` / `DTEND` 用 UTC；没有结束时间时用片长，片长也没有就按 2 小时并在备注里说明；`UID` = 场次 id，重复导入不会多出一条）。地点按场次的 `screen` 匹配 `location.places`（没有 `screen` 的场外场次——Coolidge 的户外放映——改用系列和片名匹配），否则用影院的 `location`；`LOCATION` 是「名称, 地址」，另写 `GEO` 和 `X-APPLE-STRUCTURED-LOCATION`（`X-TITLE` 必须与 `LOCATION` 相同，Apple 日历才显示地图）。文件以 `data:text/calendar` 链接交出：iOS Safari 直接弹出日历的「添加」，桌面浏览器下载后打开即导入；iOS 上的其他浏览器和微信等内置浏览器不把 .ics 交给日历，改为提示用 Safari 打开。没有 `location` 的影院只写影院名。同一事件对象另生成 Google 日历链接（`googleUrl`）：手机用 `calendar.google.com/calendar/render?action=TEMPLATE`，电脑用 `/calendar/r/eventedit`，参数 `dates`（UTC）/ `text` / `location`（「名称, 地址」文本，Google 没有结构化地点）/ `details`；用户在 Google 的页面里确认并保存，本站不接触任何 Google 账号。弹窗里是「购票 · 详情 · 加入日历 ▾」一行：有鼠标的设备悬停「加入日历」弹出 Apple / Google 两项，手机上点按展开、再点或点别处收起（悬停只在 `(hover: hover)` 的设备上生效，避免手机点按后残留的 :hover 让菜单关不掉；「×2」的影厅框同理）。
* **数据状态提示**：影院按钮上的黄点表示旧数据，红点表示失败，蓝点表示来自兜底源；兜底来的场次带 "via <兜底源>" 标记。列表视图里影院名链接到 `website`。
* **界面语言**：中 / 英切换（`I18N` 词典 + `t()`；静态文本用 `data-i18n*` 属性）。默认跟随浏览器语言，也可用 `lang=en` 参数指定，选择会被记住。
* **时区**：每家影院按自己的 `timezone` 建 `Intl.DateTimeFormat`，时间轴每行的刻度是该影院的本地时钟；所有行同一时区时画一条「现在」线，否则每行各画一个标记。「今天」按浏览者本地日期取，各影院的场次按各自的 `day` 归组，不会错位。弹窗里对与浏览者不同时区的影院注明时区缩写（如 `7:00pm PDT`）。
* **其他**：时间显示只用 `Intl.DateTimeFormat`。窄屏下时间轴改为纵向（时间向下，影院成列）。深色模式跟随系统。可「添加到主屏幕」（manifest + apple-touch-icon）。

## 8. 调度与发布

### 8.1 本机（每个拷贝，包括作者实例）

* **`python -m scraper.update`**：一次完整更新，所有系统通用。
  1. 抓取（`scraper.run --no-export`，自带运行锁）；`--repair` 或 `AUTO_REPAIR=1` 时用 `scraper.repair --failed` 修复失败的配方影院。
  2. 导出，清理 14 天前的原始快照。
  3. **只有加 `--publish` 时**才调用 `publish.sh`，所以任何人的定时任务都不会发布到作者的网站。
  日志写入 `logs/refresh.log`，超过 5 MB 时只保留最后 2 万行。
* **`python -m scraper.schedule on | off | status`**：按当前文件夹的实际路径生成并安装系统自带的定时任务，默认 01:00 / 13:00（本机时间，`--times` 可改），命令都是 `.venv` 里的 Python 运行 `scraper.update`：
  * macOS：LaunchAgent `com.corridor-showtimes.update`（`WorkingDirectory` 为项目文件夹；睡眠时错过的运行在唤醒后补跑；Aqua 会话，MoMA 的浏览器路径可以开窗口）。
  * Windows：任务计划程序「Corridor Showtimes update」（`StartWhenAvailable` 补跑错过的运行；`pythonw.exe` 不弹控制台窗口；用电池时也运行）。
  * Linux：systemd 用户定时器（`Persistent=true` 补跑）；没有 systemd 时写入 crontab（带标记行，`off` 只删自己的行）。
  * `status` 报告是否开启、指向哪个文件夹、数据最后更新时间和最近一次运行结果；加影院向导结束时也报告（`--json` 输出里的 `auto_update`）。
  * 配置生成都是纯函数（`launchd_plist`、`windows_task_xml`、`systemd_units`、`cron_block`），离线测试覆盖三个平台。
* **网页提醒**：数据超过 36 小时没更新时，「更新于」变成警告色；在本地打开（`file://`）时还会提示「自动更新可能没开」和开启方法。线上网站只变色，不提示。
* **作者实例**：`schedule on --publish`（或旧的 `com.cinema.refresh` 任务调用 `scripts/refresh.sh`，效果相同），每次更新后发布到 GitHub Pages。`schedule on` 发现旧任务时会拒绝重复安装，`--replace-legacy` 用新任务替换它。
* **`scripts/publish.sh`**：把 `site/` 的网页文件和最新 `data.js` 组装成一个**孤立提交**（orphan commit），强制推送到 `gh-pages` 分支，由 GitHub Pages 提供服务。发布前 `scripts/stamp_assets.py` 给暂存副本里 index.html 引用的 `styles.css` / `data.js` / `calendar.js` / `app.js` 加上内容版本（`app.js?v=<sha256 前 10 位>`）：Pages 让浏览器缓存 10 分钟，带版本后普通刷新（重新校验 index.html）就能拿到配套的新文件，不会出现新数据配旧脚本；工作目录里的 site/ 不改。CI 组装 `_site/` 时同样处理。每次发布都替换上一次，仓库不会因每日更新而膨胀。凭证由仓库本地的 `gh auth git-credential` 提供。
* **项目位置**：macOS 上项目必须放在「下载」「文稿」「桌面」和 iCloud 云盘之外，因为隐私保护（TCC）不允许 launchd 任务读取这些位置；`schedule on` 按真实路径（解析快捷方式后）检查，发现就拒绝并提示移动文件夹。

### 8.2 GitHub Actions（可选，默认关闭）

给想把自己那份放在 GitHub 上的人用。`.github/workflows/refresh.yml` 只有在仓库变量 `CLOUD_REFRESH` 为 `true` 时运行（避免覆盖由本机 `publish.sh` 发布的站点），还需要 Settings → Pages 选 GitHub Actions。

* 触发：`schedule: 0 5,17 * * *`（UTC，= 纽约 1:00 / 13:00）+ `workflow_dispatch`。
* 步骤：checkout → Python 3.12 → `pip install -e ".[llm]"` → `configure-pages` → **恢复状态**（`python -m scraper.store --seed <Pages 地址>/showtimes.json`，首次运行没有就从空库开始）→ `CINEMA_NO_BROWSER=1 python -m scraper.run --no-export` →（有 `ANTHROPIC_API_KEY` 时）修复失败的配方 → `scraper.export` → 组装 `_site/`（网页 + `data.js` + `showtimes.json`）→ `upload-pages-artifact` + `deploy-pages`。可选 Secrets：`TMDB_TOKEN`、`ANTHROPIC_API_KEY`。
* 云端的已知情况：Metrograph 对数据中心 IP 限速更严（有 screenslate 兜底）；需要浏览器的影院一律走兜底或标为旧数据。

## 9. 如何新增一家影院

公开站点只收录作者的影院；其他人在**自己电脑上的一份拷贝**里加影院。不运行服务器、不代付任何费用：抓取在用户电脑上跑，技术工作交给用户自己的 AI 编程助手。

1. **网页上的「自定义影院」按钮**：弹窗里是一份五步的小白教程（中英文随网页语言切换）：准备能运行程序的 AI 助手（Claude Code / Cursor / Codex，只能聊天的不行）→ GitHub 上 Code → Download ZIP 并解压 → 在助手里打开文件夹，发送「请阅读这个文件夹里的 AGENTS.md，帮我添加一家影院。」→ 按提示回答 → 打开 `site/index.html`。弹窗链接到 README 的完整教程（含「助手会说什么、怎么回答」的对照表）与求助 Issue 模板。
2. **`AGENTS.md`**（Claude Code 通过 `CLAUDE.md` 的 `@AGENTS.md` 读取）：规定助手的固定流程——用用户的语言、少术语；一次问清影院名、排片页网址、城市；安装环境（没有 Python 3.12 时经用户同意装 uv）；把城市换成时区后运行 `scraper.add --tz … --lang …`；按向导的四种结论处理（成功 → 抓取全部并打开网页；需要配方 → 按 `handoff/<id>/BRIEF.md` 写并验证；被拦截 → 说明原因，纽约 / 旧金山可只用 screenslate；没有场次 → 要排片页链接重试）；说明数据只在本机、不会自动更新；实在不行时帮用户整理内容去 GitHub 提 Issue（`.github/ISSUE_TEMPLATE/help-add-cinema.yml`，不触发任何自动化）。
3. **会命令行的人**直接用 `python -m scraper.add "影院名" <排片页网址> [--tz …] [--region …]`；Claude Code 用户可用 `/add-venue "影院名" <网址>`。

手写时：`venues.yaml` 加一条，`source:` 先考虑平台适配器（参数见 `PLATFORMS.md`），再考虑配方（`scraper/recipes/<id>.yaml`），最后才写 `scraper/sources/<id>.py`（继承 `BaseScraper`，实现 `fetch` / `parse`，`@register("<id>")`，时间一律 `to_local(dt, self.tz)` / `iso(dt, self.tz)`；需要详情页时实现 `enrich`，用 `enrich_by_url`，自带缓存）。然后 `python -m scraper.add --verify <id>` 保存 fixture 并跑契约，`pytest tests/test_contract.py -k <id>`。screenslate 收录的话，加 `fallback: {adapter: screenslate, nid: …}`。

**面向外行的边界**：向导输出、网页上的教程、配置错误都有中英两版，不出现堆栈（堆栈进日志）；README 的适配器表写明每个适配器「数据来自影院的 X 系统，本项目只读取其公开页面 / feed」，以及 Eventive key、Agile 缓存要求的使用边界；绝不实现绕过 Cloudflare / Sucuri / 验证码的逻辑，向导遇到就直说。

## 10. 已知风险

| 风险 | 缓解 |
|---|---|
| Metrograph 按 IP 限速 / 封禁 | 每次运行只请求一次；429 / 403 立即停止；2 小时冷却；兜底 screenslate |
| MoMA 的 Cloudflare 挑战 | 持久 profile；失败走兜底；20 小时冷却，约每天只试一次浏览器 |
| screenslate 拒绝 Python 的 TLS 握手 | 该源走系统 curl |
| PFS 官网被防火墙拦截 | 改用售票系统的公开 feed；GUID 变化时按 README 重新查找 |
| 页面改版导致解析为 0 或字段错位 | 0 条判失败并保留旧数据；条数骤降打 WARN；原始快照可回溯；每个源都有离线测试 |
| Film Forum 时间没有上午 / 下午 | 规则推断（11 点 = 上午，12 = 中午，1–10 = 下午）+ 单测 |
| TMDB 配错片 | 保守匹配规则；错的条目可在 `data/cache/tmdb.json` 删除后重查 |
| 平台改版导致某个适配器整体失效 | 每个平台有真实样本的离线测试；每家影院独立 stale；README 记录各平台最近验证日期 |
| 配方过度设计成「又一个模板语言」 | 只实现 §5.7 列出的原语；配方表达不了的转 custom，不扩语法 |
| LLM 生成的配方偶然正确（碰巧匹配当天页面） | 三轮验证要求 ≥ 80% 条目命中且日期分布合理；`--verify` 存 fixture 后由契约测试长期看守 |
| Agile feed GUID 依赖影院配合 | 探测只认能返回场次的入口 GUID；找不到时向导明说，并用配方抓官网作为过渡 |
| Eventive key 的使用边界 | 只用影院自己公开页面里的 key；README 声明；影院要求时移除 |
| CI 无状态 | 从上次发布的 `showtimes.json` 回灌（冷却记录不回灌：云端每次都会先试主源） |
| 数据中心 IP 被限速 / 没有浏览器 | 兜底源 + stale 标记；README 说明本机运行更稳 |
| 影院数量增长 | `data.js` 是单文件；超过约 100 家时需要按区域拆分导出（尚未实现） |

# Corridor Showtimes — 架构

纽约 + 费城九家艺术 / 重映影院的排片聚合器：每天抓取两次，合并成统一数据，以时间轴 / 列表 / 周三种视图展示，并发布到 GitHub Pages。每家影院网站的抓取细节见 [`SOURCES.md`](SOURCES.md)。

## 1. 核心设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12（httpx、BeautifulSoup/lxml、Playwright） | 抓取生态最成熟 |
| 前端 | 纯静态 HTML + 原生 JS，无框架、无构建步骤 | 易于修改；可直接部署为静态站点 |
| 数据流 | 抓取 → SQLite → 导出 `site/data.js` | 用 `<script src="data.js">` 注入全局变量，网页从 `file://` 打开也能用（`fetch` 在 file:// 下不可用） |
| 调度 | macOS `launchd`，每天 01:00 和 13:00（纽约时间） | 01:00 避开影院自己的午夜发布；影院通常在白天更新下周排片，13:00 再抓一次 |
| 抓取位置 | 本机，而非云端 CI | Metrograph 对数据中心 IP 限速更严；费城影院的防火墙会拦截云服务器 |
| 时区 | 一律存 ISO 8601 带偏移，固定 `America/New_York` | 所有影院都在美东 |
| 失败策略 | 每家影院独立；失败时保留上次成功的数据并标记 stale | 旧数据加提示，好过一片空白 |
| 兜底源 | screenslate.com 开放的 JSON:API | 主源失败时自动替换，并在界面上标注 |
| 可扩展性 | `config/venues.yaml` 一条 + `scraper/sources/<id>.py` 一个文件 | 加一家影院不改其他代码 |

## 2. 目录结构

```
├── config/venues.yaml          影院注册表（§4）
├── scraper/
│   ├── models.py               Screening / VenueStatus / VenueConfig
│   ├── base.py                 BaseScraper、HTTP 客户端（httpx / curl 两种传输）、Playwright 浏览器会话、详情页缓存
│   ├── registry.py             @register("<id>") 装饰器，按 venues.yaml 装配
│   ├── normalize.py            时间解析、全大写标题转换、语言文字解析、稳定 id
│   ├── language.py             语言补全：影院文本 → TMDB → 默认值（§5.5）
│   ├── store.py                SQLite 读写
│   ├── export.py               SQLite → data/showtimes.json + site/data.js
│   ├── run.py                  命令行入口：抓取、校验、兜底、冷却、写库、导出
│   └── sources/                每家影院一个文件，外加 screenslate.py（兜底）
├── site/                       index.html / app.js / styles.css / 图标与 manifest（data.js 为生成物）
├── scripts/
│   ├── refresh.sh              定时任务入口：抓取 → 导出 → 清理 → 发布
│   ├── publish.sh              把 site/ 推到 gh-pages 分支
│   ├── com.cinema.refresh.plist  launchd 配置
│   ├── open_site.sh / make_app.py  本机双击打开的 macOS 小程序
├── tests/                      离线解析测试 + 真实页面 fixtures
├── data/                       （不入库）SQLite、原始快照、详情页缓存、浏览器 profile、TMDB 缓存
└── logs/                       （不入库）运行日志
```

## 3. 数据模型

### 3.1 `Screening`：一场放映（一个影院 × 一个开始时间 × 一个节目）

| 字段 | 说明 |
|---|---|
| `id` | `sha1(venue_id|start|规范化标题)[:16]`，跨次抓取稳定 |
| `venue_id` | venues.yaml 里的 key |
| `title` | 展示用标题；全大写来源（Film Forum、Anthology、PFS）统一转换大小写 |
| `start` / `end` | ISO 8601 带偏移；`end` 来自影院或 start + 片长，没有则为空 |
| `day` | 本地日期，前端按天索引 |
| `director` / `year` / `runtime_min` | 可选 |
| `format` | `35mm` / `16mm` / `70mm` / `DCP` / `Film`（胶片但规格未知）等 |
| `language` | `"Japanese"`、`"French, Wolof"`、`"Silent"`、`"Opera (subtitled)"`；空 = 未知 |
| `series` / `screen` / `note` | 影展或系列、影厅、备注（"Q&A with…"、"Sold out"） |
| `detail_url` / `ticket_url` | 影院自己的影片页和购票页 |
| `source` | `primary` 或 `screenslate` |

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
- id: metrograph
  name: Metrograph
  short: MG                  # 顶部按钮上的缩写
  city: NYC
  color: "#e63946"
  scraper: metrograph        # scraper/sources/<scraper>.py
  enabled: true
  screenslate_nid: 6         # 兜底源里的影院编号；没有则 null
  horizon_days: 30           # 只保留今天起多少天
  rate_limit_s: 3            # 同一域名两次请求的最小间隔
  primary_cooldown_h: 2      # 主源失败后多少小时内直接用兜底
  # 可选：allow_empty、default_language、browser.{headless, challenge_timeout_s}、agile_guid
```

| 影院 | 抓取方式 |
|---|---|
| BAM Rose Cinemas | JSON API + 详情页补全 |
| Film at Lincoln Center | 官网背后的 JSON API |
| Japan Society | WordPress 自定义端点 |
| Anthology Film Archives | 服务端 HTML，按月 |
| Film Forum | 服务端 HTML，7 天 + 详情页补全 |
| Metrograph | 服务端 HTML，单页（每次运行只请求一次） |
| L'Alliance New York | 列表卡片 + 每场详情页 |
| MoMA | Playwright 浏览器；通常回退到 screenslate |
| Philadelphia Film Society | 售票系统 Agile Ticketing 的公开 JSON feed |

## 5. 抓取层

### 5.1 `BaseScraper`

```python
class BaseScraper:
    needs_browser = False       # True：通过共享的 Playwright 会话取页面
    transport = "httpx"         # "curl"：对拒绝 Python TLS 的站点（screenslate）
    def fetch(self) -> list[RawPage]            # 只做网络 IO
    def parse(self, pages) -> list[Screening]   # 纯函数，离线可测
    def enrich(self, screenings) -> None        # 可选：详情页补字段，失败不致命
    def run(self) -> (screenings, VenueStatus)  # fetch → 保存原始快照 → parse → enrich
```

`fetch` 与 `parse` 严格分离：测试直接用 `tests/fixtures` 里的真实页面调用 `parse`，不联网。
需要月份 / 年份推断的解析器（Film Forum、MoMA）以页面的抓取日期为基准，保证测试结果不随运行日期变化。

### 5.2 HTTP 客户端

* **请求头与重试**：固定桌面 Chrome UA，超时 30s；遇到 5xx / 网络错误时指数退避，最多重试 3 次。
* **429 立即停止**：该影院本次不再请求。
* **限速**：同一域名两次请求之间按 `rate_limit_s` 间隔。
* **原始快照**：每个响应原文写入 `data/raw/<date>/<venue>[_n].<ext>`，保留 14 天，便于回溯解析问题。
* **详情页缓存**：原始 HTML 缓存在 `data/cache/<venue>/`，7 天有效。缓存的是原文而不是解析结果，所以解析器修复后对缓存立即生效。

### 5.3 浏览器路径（MoMA）

* **会话**：共享 Chromium 会话，profile 持久化在 `data/browser_profile/`，Cloudflare 的 clearance cookie 可以复用。
* **判定失败**：页面停在挑战页超过 `challenge_timeout_s` 即算失败。浏览器被关闭、崩溃、超时一律转成一行错误信息，不打印堆栈。
* **不绕过**：不做任何绕过防护的处理，失败即走兜底。

### 5.4 兜底与冷却（`run.py`）

```
for venue in enabled venues:
    if 主源在冷却期内:            跳过主源
    else:                        result = primary.run(); validate(result)
    if 失败 and venue.screenslate_nid:
        result = ScreenslateScraper(venue).run()      # source = "screenslate"
    fill_languages(result)
    store.apply(result)
```

* **校验**：
  * 解析出 0 条视为失败，配置了 `allow_empty` 的影院除外。
  * 条数比上次骤降 70% 以上时写入，但打 WARN。
  * 超出有效时间窗的行丢弃；过去日期静默丢弃，太远的未来打 WARN。
* **冷却（`primary_cooldown_h`）**：主源失败后的一段时间内直接用兜底，避免反复请求刚封禁过我们的网站（Metrograph），也避免每次运行都开浏览器（MoMA）。
* **运行锁**：`data/.run.lock`（`flock`）保证同一时间只有一个写库的运行。手动运行和定时任务互不冲突。

### 5.5 语言补全（`language.py`）

为「非英语（有字幕）」筛选服务。优先级：

1. **影院网站自己的文字**："In French and Wolof with English subtitles"、"silent"、PFS feed 的 Original Language。
2. **歌剧 / 芭蕾直播**（按系列名或备注识别）：直接标为 `Opera (subtitled)`，不查 TMDB，免得配到同名电影。
3. **TMDB 查询**（需 `config/tmdb_token.txt`）。宁可「未知」，不要配错：
   * 先清理片名：去掉 "EC: "、"X Presents: "、"w/ Q&A"、"(4K Restoration)"，以及冠词前的「导演名's」。
   * 讲座、短片合集、连映不查。
   * 有年份时要求 ±1 年内，同年优先；仍有多个候选时用导演核对。
   * 没有年份时，先借用其他影院同名片的年份和导演；再优先当年的新片；所有候选语言相同时直接采用；有一部热度是第二名 3 倍以上时取它；都不满足就放弃。
   * 结果缓存在 `data/cache/tmdb.json`：命中的永久保存，未命中的 14 天后重试。
4. **影院默认语言**（`default_language`：Japan Society = 日语，L'Alliance = 法语）。

### 5.6 命令行

```
python -m scraper.run                                   # 全部影院 + 导出
python -m scraper.run --venue metrograph --dry-run      # 只打印解析结果
python -m scraper.run --venue moma --source screenslate # 强制兜底；--source primary 关闭兜底
python -m scraper.run --venue filmforum --parse-fixture tests/fixtures/filmforum/now_playing.html
python -m scraper.export                                # 只重新导出
```

## 6. 导出格式 `site/data.js`

```js
window.CINEMA_DATA = {
  generated_at: "2026-09-28T05:08:56Z",
  venues: [ { id, name, short, color, city, status, fetched_at, count, horizon_end, error, source } ],
  screenings: [ { ...Screening（不含 scraped_at） } ],   // 只导出昨天及以后
  days: { "2026-09-28": [screening_id, ...], ... }     // 按天索引
};
```

同时写 `data/showtimes.json`（同结构的纯 JSON）。

## 7. 前端 `site/`

单页、无框架、无构建。所有 DOM 由 `app.js` 里的几个 `render*` 函数从 `window.CINEMA_DATA` 与一个 `state` 对象派生。

* **视图**：
  * 时间轴（默认）：每家影院一行，重叠的场次用贪心算法分道（lane packing）；块宽 = 片长，片长未知时按 100 分钟画成虚线框。点击出详情弹窗。
  * 列表：按影院分组，同一节目的多个场次合为一行。
  * 周：7 列，从周四开始，也可从今天开始。点片名跳到当天时间轴并高亮。
* **筛选**：影院多选、只看胶片、非英语（有字幕）、隐藏已开场、片名 / 导演搜索。「非英语」筛选会显示因语言未知而隐藏的场次数。
* **状态**：放在 URL hash（`#/2026-10-03?view=list&v=bam,filmlinc&sub=1`），刷新和分享都保留。影院选择另存 `localStorage`；新加入的影院自动选中。
* **数据状态提示**：影院按钮上的黄点表示旧数据，红点表示失败，蓝点表示来自 screenslate；兜底来的场次带 "via screenslate" 标记。
* **界面语言**：中 / 英切换（`I18N` 词典 + `t()`；静态文本用 `data-i18n*` 属性）。默认跟随浏览器语言，也可用 `lang=en` 参数指定，选择会被记住。
* **其他**：时间显示只用 `Intl.DateTimeFormat`，固定 `America/New_York`。窄屏下时间轴改为纵向（时间向下，影院成列）。深色模式跟随系统。可「添加到主屏幕」（manifest + apple-touch-icon）。

## 8. 调度与发布

* **`scripts/refresh.sh`**（launchd 每天 01:00 / 13:00 调用；Mac 睡眠时错过的运行在唤醒后补跑）依次做这几件事：
  1. 抓取并导出。
  2. 清理 14 天前的原始快照。
  3. 调用 `publish.sh`。
  日志写入 `logs/refresh.log`，超过 5 MB 时截断。
* **`scripts/publish.sh`**：把 `site/` 的网页文件和最新 `data.js` 组装成一个**孤立提交**（orphan commit），强制推送到 `gh-pages` 分支，由 GitHub Pages 提供服务。每次发布都替换上一次，仓库不会因每日更新而膨胀。凭证由仓库本地的 `gh auth git-credential` 提供。
* **项目位置**：项目必须放在 `~/Downloads`、`~/Documents`、`~/Desktop` 之外，因为 macOS 的隐私保护（TCC）不允许 launchd 任务读取这些目录。

## 9. 如何新增一家影院

1. 在 `config/venues.yaml` 加一条。
2. 新建 `scraper/sources/<id>.py`：继承 `BaseScraper`，实现 `fetch` 和 `parse`，用 `@register("<id>")` 注册；需要详情页补全时实现 `enrich`（用 `enrich_by_url`，自带缓存）。
3. `python -m scraper.run --venue <id> --dry-run` 检查结果；把 `data/raw/<date>/<id>*` 复制到 `tests/fixtures/<id>/`，写 `tests/test_<id>.py`。
4. screenslate 收录的话，填上 `screenslate_nid`，主源失败时就会自动兜底。

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

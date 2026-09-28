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

设计见 `ARCHITECTURE.md`，每家网站的抓取细节和坑见 `SOURCES.md`。

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
.venv/bin/python -m scraper.run --venue moma --source screenslate   # 强制用兜底源
.venv/bin/python -m scraper.run --venue moma --source primary       # 只用主源，不兜底
.venv/bin/python -m scraper.run --venue filmforum --parse-fixture tests/fixtures/filmforum/now_playing.html
.venv/bin/python -m scraper.export                       # 只重新生成 site/data.js
.venv/bin/pytest -q                                      # 离线测试（不联网）
```

---

## 新增一家影院

1. 在 `config/venues.yaml` 加一条（`id`、`name`、`short`、`color`、`scraper`，其余字段见文件里的例子）。
2. 新建 `scraper/sources/<scraper>.py`：继承 `BaseScraper`，实现 `fetch()`（只联网）和 `parse()`（纯解析，可离线测试），类上加 `@register("<scraper>")`。需要导演 / 片长但列表页没有时，再实现 `enrich()`，用 `self.enrich_by_url(...)` 抓详情页（自动缓存 7 天）。
3. `python -m scraper.run --venue <id> --dry-run` 看结果。
4. 把 `data/raw/<日期>/<id>*.html|json` 复制到 `tests/fixtures/<id>/`，写 `tests/test_<id>.py`。
5. 如果 screenslate 收录了它，查 nid 填进 `screenslate_nid`，主源失败时会自动兜底：
   `curl -s 'https://www.screenslate.com/jsonapi/node/venue?filter[title]=<影院名>'`

`venues.yaml` 里可选的字段：

| 字段 | 作用 |
|---|---|
| `horizon_days` | 只保留今天起多少天内的场次 |
| `rate_limit_s` | 同一网站两次请求的最小间隔 |
| `allow_empty` | 抓到 0 场也算成功（片少的影院） |
| `screenslate_nid` | 主源失败时用 screenslate 兜底 |
| `primary_cooldown_h` | 主源失败后多少小时内直接用兜底（MoMA 用它避免每次都开浏览器） |
| `browser.headless` / `browser.challenge_timeout_s` | 需要浏览器的影院（MoMA） |
| `default_language` | 网站和 TMDB 都没有语言时的默认值 |

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
`filmadelphia.org` 整站被防火墙拦截（浏览器也会被判为机器人），所以改用它的售票系统 Agile Ticketing 公开的 JSON feed（官方提供，每 10 分钟更新）。如果哪天 feed 返回空或 404，可能是 GUID 换了：搜索 `prod5.agileticketing.net entrypoint.aspx "Philadelphia Film Society - EVENTS"` 找新的 GUID，填到 `venues.yaml` 的 `agile_guid`。

**定时任务没跑**
`launchctl print gui/$(id -u)/com.cinema.refresh | grep -E "state|last exit"`；退出码 127 = 路径或权限问题（见上面的文件夹说明）。launchd 自己的输出在 `logs/launchd.err.log`。

**Playwright 报要 `playwright install`**
`pyproject.toml` 把 Playwright 锁在 1.62.0，对应本机已有的 Chromium。换机器时运行一次 `.venv/bin/python -m playwright install chromium`。

---

## 目录

```
config/venues.yaml        影院注册表
scraper/                  抓取、存储、导出（sources/ 下每家一个文件）
site/                     网页（index.html / app.js / styles.css；data.js 是生成物）
data/                     showtimes.sqlite、showtimes.json、raw/ 原始快照、cache/ 详情页缓存、browser_profile/
scripts/refresh.sh        定时任务调用的脚本
scripts/com.cinema.refresh.plist   launchd 配置
logs/refresh.log          运行日志
tests/                    离线解析测试 + fixtures
```

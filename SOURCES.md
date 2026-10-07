# 影院数据源实测手册

> 2026‑09‑24 用 curl（桌面 Chrome UA）实测。每节给出：入口 URL、渲染方式、单条数据的结构、覆盖范围、拦截情况、推荐解析策略。编写 `scraper/sources/<id>.py` 时以此为准；页面改版时请重新探测并更新本文件。

通用约定：
- UA：`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36`
- 所有时间解析后转成 `America/New_York` 的 ISO 8601。
- 「难度」：★ 开放 JSON / ★★ 服务端 HTML / ★★★ 需要浏览器 / ★★★★ 基本抓不到。

---

## 1. BAM Rose Cinemas — ★ JSON API

**入口**
```
GET https://www.bam.org/api/BAMApi/GetCalendarEventsByDayWithOnGoing?start=9/24/2026&end=12/23/2026
```
- `start` / `end` 为美式 `M/D/YYYY`，**不补零**。任意区间都行；取 `today` 到 `today + horizon_days`。
- 无需 cookie / UA，无 Cloudflare。

**单条**（一部片一天一条，多场次在 `performances` 数组里）
```json
{"performances": ["2026-09-24T17:00:00-04:00","2026-09-24T21:20:00-04:00"],
 "performancesShort": ["5pm","9:20pm"],
 "id": 58217, "day": "2026-09-24", "genres": "Film", "name": "Tony",
 "desc": "...", "img": "/globalassets/...",
 "buyLink": "https://commerce.bam.org/production/58217",
 "moreLink": "/film/2026/tony", "onGoing": false}
```

**解析**
- 只保留 `genres` 包含 `Film` 的（存在 `"Kids,Film"`、`"Opera,Film"` 这类复合值）。
- 每个 `performances[i]` 展开为一条 Screening，`start` 直接用（已带偏移）。
- `detail_url = "https://www.bam.org" + moreLink`，`ticket_url = buyLink`。
- 导演 / 年份 / 时长不在 API 里。可选增强：GET `moreLink` 详情页，页面里有 JSON‑LD `{"graph":[{"@type":"Event","startDate","endDate","location":{"name":"BAM Rose Cinemas at BAM KBH"}}]}`，`runtime = endDate - startDate`；`<h2>RUNNING TIME</h2>` 后面是 "126min"。每部片只请求一次并按 `moreLink` 缓存。

**实测补充（2026‑09‑24）**：详情页纯文本里 `Directed by X\n(2026)`、`Part of\nSeries`、`RUNNING TIME\n106min`、`FORMAT\nDCP` 都能取到，已在 `enrich()` 里接入；"BAM Film 2026" 这种泛化系列名丢弃。详情页 HTML 缓存在 `data/cache/bam/`，7 天内不重复请求；三天内开场的片每天重新取一次，因为日程和嘉宾常在最后几天才补上。

**实测补充（2026‑10‑07，一整天的活动）**：日历 API 里一场「12:01pm」的 Black Women's Film Conference，详情页简介里才有 `Schedule:` 日程——时间一行（`12pm`、`12:15 pm`、`1:45pm`），下面是这一段的内容，电影段和开场致辞、对谈、休息、Town Hall 交替。活动只有一场（`performances` 只有一个）、日程第一段离这场开场不超过 90 分钟、时间往后排时，拆成每个电影段一条：电影行带导演（`Heat dir. Aicha Cherif`、`dir` 也可能不带点）或年份（`Boyant (2008)`），没有这两样的段（致辞、对谈、休息）不收。一段只有一部片时用片名；多部片（短片合集）用活动名去掉主办方（「New Negress Film Society presents」），每部片和段名（`The Works of Akosua Adoma Owusu`，同时据此填导演）写进备注。每段到下一段开始时结束，系列是原活动名。

---

## 2. Film at Lincoln Center — ★ JSON API（非官方）

`https://www.filmlinc.org/films/<slug>/` 这类是单部影片页，且 www 站整体被 Cloudflare 挑战（403），**不要抓网页**。真实数据源是他们前端调用的 API：

```
GET https://api.filmlinc.org/showtimes                # 全部，约 1.2 MB，覆盖到 2027‑06
GET https://api.filmlinc.org/showtimes?date=2026-09-25   # 单日
```
无鉴权，无挑战。其他参数（start/end/venue/slug）都被忽略。

**结构**
```json
{"queueStatus": {...},
 "films": [
   {"id":"84108","title":"9 Temples to Heaven","slug":"9-temples-to-heaven",
    "showtimes":[
      {"id":"84155","date":"2026-10-07","time":"9:00 PM",
       "dateTimeET":"2026-10-07T21:00:00-04:00",
       "venue":"Walter Reade Theater","available":false,"status":"standby",
       "ticketsUrl":"https://purchase.filmlinc.org/84108/84155",
       "openCaptions":false,"freeEvent":false,"specialEvent":false,
       "saleStartDateET":"2026-09-25T12:00:00-04:00"}]}]}
```

**解析**
- 一次 GET 全量，展开 `films[].showtimes[]`；`start = dateTimeET`；`screen = venue`。
- **过滤非放映条目**：`title` 匹配 `/pass|voucher|membership|package/i` 的丢弃（例如 "2026 NYFF Express Pass"）。
- `venue` 里会出现合作场地（BAM、Museum of the Moving Image、Alamo Staten Island、Alice Tully Hall）。保留 `screen` 原值；`venue_id` 仍是 `filmlinc`。前端可按 `screen` 二级筛选，暂不做。
- 无导演 / 年份 / 时长。`detail_url = https://www.filmlinc.org/films/{slug}/`（供读者点击，程序不抓）。

**实测补充**：过滤正则要带复数（`vouchers?` 等，实测有 "2026 NYFF Volunteer Vouchers"）。`showtimes[].presaleSchedule.presaleType` 为 `nyff` / `met-guild` 时分别映射为系列「New York Film Festival」/「Met Opera Live in HD」。同名影片会以两个 film 条目出现（NYFF 场 + 正式上映），不是重复。API 没有片长 / 导演，也没有单片端点（`/films/<slug>` 404），时间轴按默认 100 分钟虚线画。

**实测补充（2026‑09‑30）**
- 官网的影片页（如 `/nyff2026/films/<slug>/`）有导演、片长、语言，但对程序请求仍返回 Cloudflare 挑战页（403 "Just a moment…"），`/wp-json/` 也被重定向。`api.filmlinc.org` 只有 `/showtimes` 一个端点（`/films`、`/film/<id>`、`/productions/<id>` 都 404）。所以导演和片长靠 TMDB 和 screenslate 补。
- 纽约电影节的外区加映是单独的条目，片名带地名：`"Bucking Fastard Bronx"`（AMC Bay Plaza Cinema）。片名是「另一条目的片名 + 1–3 个词」，或以纽约各区名结尾时，去掉地名放进备注，系列沿用主条目的。

---

## 3. Japan Society — ★ JSON（WordPress 自定义端点）

```
GET https://japansociety.org/wp-json/events/v1/data?events_categories=9127
```
- `9127` = Film；`10825` = Film Series；`9194` = Monthly Classics。可逗号连接：`events_categories=9127,10825,9194`。
- 返回所有未来活动（当前 39 条到 2027‑05），无需日期参数。`limit` 无效。
- Cloudflare 存在但不挑战 curl。

**单条**
```json
{"id":78393,"title":"Hirayasumi Anime – Exclusive Early Look at Episode 1",
 "permalink":"https://japansociety.org/events/hirayasumi-anime-.../",
 "terms":{"events_categories":[{"id":9127,"name":"Film","slug":"film"}]},
 "days":{"all_day":false,"type":"single_day","milti_day_events":null,
   "single_day_events":[{"date":"October 7, 2026","time_start":"7:00 pm","time_end":""}]},
 "month_keys":["October 2026"],"sold_out":false}
```
多日活动：`"type":"multi_day","milti_day_events":{"date_start":"October 6, 2026","date_end":"December 15, 2026","time_start":"","time_end":""}`（注意 `milti` 是他们的拼写错误，照抄）。

**解析**
- `single_day_events[]` 每项一条：`strptime(f"{date} {time_start}", "%B %d, %Y %I:%M %p")`。
- `multi_day` 且无 `time_start` 的通常是展览 / 系列容器，**跳过**（真正的放映都会以 single_day 形式再出现）。
- `screen = "Japan Society"`。
- 可选增强：GET `permalink`，正文有 `Dir. Mikio Naruse, 1955, 123 min., 35mm` 这类自由文本，正则 `Dir\.\s*(.+?),\s*(\d{4}),\s*(\d+)\s*min\.?,?\s*([0-9A-Za-z]+)?`；购票链接指向 `boxoffice.japansociety.org`。页面上的 JSON‑LD `startDate` 恒为 1970，不可用。
- 电影本来就少，配置 `allow_empty: true`。

**实测补充**：只算 Film 类（`9127,10825,9194`）时当前只有 1 条；上面说的 39 条是全部类别的活动。

---

## 4. Anthology Film Archives — ★★ 服务端 HTML，按月

```
GET https://www.anthologyfilmarchives.org/film_screenings/calendar?view=list&month=9&year=2026
```
- `month` 可不补零。无参数时返回月历视图（无用）。
- 抓 **当月 + 后两个月**，某月解析出 0 个 `div.film-showing` 就停。实测 9 月 68 场、10 月 86 场、11 月 3 场，排片提前约 5–6 周。
- 无 JSON，无 JSON‑LD，RSS 没有日期。Cloudflare 放行 curl。

**单条**（日期来自前面的 `h3.current-day`，年月来自 URL）
```html
<a name="day-02"></a>
<h3 class="current-day">Wednesday, September  2 ...</h3>
<div class="film-showing clearfix">
  <div class="showing-details">
    <a name="showing-61981"> 6:30 PM</a><br/>
    <span class="film-title">UNIONDOCS PRESENTS: WELFARE</span><br />
    by Frederick Wiseman<br />
    1975, 167 min, 16mm-to-DCP <br/>
    <span class="share-toggle">Share +</span>
    <div class="share-box">... <a href="...calendar?view=list&month=9&year=2026#showing-61981">URL</a> ...</div>
    <div class="film-notes"><img .../><p>notes...</p>
      <a href="https://ticketing.us.veezi.com/sessions/?siteToken=...">tickets</a></div>
    <p class="series-note"><strong>This screening is part of: SERIES NAME</strong></p>
  </div>
</div>
```

**解析**
- 按文档顺序遍历，遇到 `h3.current-day` 更新「当前日期」（正则取 `\d{1,2}`，注意双空格），遇到 `div.film-showing` 产出一条。
- 时间：`a[name^="showing-"]` 的文本，`%I:%M %p`。`showing-NNNNN` 是稳定 id，可用作 `detail_url` 锚点。
- `span.film-title` 后的裸文本节点：`^by (.+)$` → director；`(\d{4}),\s*(\d+)\s*min,\s*(.+)$` → year / runtime / format。format 里 `16mm-to-DCP` 这种保留原文。
- `p.series-note strong` 去掉 "This screening is part of: " 前缀 → series。
- 票链接是通用 Veezi 页，不是单场；仍存到 `ticket_url`。

**实测补充（与上文不同之处）**
- 一个 `div.film-showing` 里可以有**多个** `a[name^="showing-"]`（如 `6:45 PM, ` + `9:00 PM`），每个都要展开。
- 元数据行前面可能有国家 / 语言前缀，后面可能有尾巴：`Mexico/Spain, In Spanish with English subtitles, 2025, 102 min, DCP`、`1925, 106 min, 35mm, silent`、`1928, 62 min, 35mm. French intertitles…`。用 `(\d{4}),\s*(\d+)\s*min` 定位，format 取之后的第一个词。
- 系列名在 `p.series-note a` 里（`strong` 里只有前缀）。
- 标题全大写，统一过 `normalize.smart_title()`。当月页面包含已过去的日期，校验时静默丢弃。

---

## 5. Film Forum — ★★ 服务端 HTML，固定 7 天

```
GET https://filmforum.org/now_playing     # 本周四到下周三
GET https://filmforum.org/coming_soon     # 未来开画日期，无场次
```
无日期参数、无法翻页。JSON‑LD 里 `ScreeningEvent` 的 `startDate` 是空字符串，不可用。

**结构**
```html
<ul aria-label="This week's showtimes at Film Forum"> THU FRI ... WED </ul>
<div id="tabs-0">
  <!-- 24 -->                                        ← 该 tab 对应的「日」
  <p><span class="alert">Ends Today!</span><strong><a href="https://filmforum.org/film/kwaidan-2026">KWAIDAN</a></strong><br />
  <span>12:50</span></p>
  <p><strong><a href="https://filmforum.org/film/my-brothers-wedding">MY BROTHER'S WEDDING</a></strong><br />
  <span>12:30</span> <span>2:20</span> <span>4:10</span> <span>6:00</span> <span>7:50</span></p>
</div>
<div id="tabs-1"> <!-- 25 --> ... </div>
```

**解析**
- `div[id^="tabs-"]` 逐个处理；日期 = 该 div 内第一个 HTML 注释里的数字（用 `bs4.Comment`）。月份推断：从今天的月份开始，若日 < 上一个 tab 的日则月份 +1。
- 每个 `p`：标题 `strong a`（全大写 → 用 `str.title()` 后修正 `Of/The/And` 等小词，或直接保留大写，二选一写死）；`detail_url = a[href]`；时间 = 所有 `span`（排除 `span.alert`）；`note = span.alert` 文本。
- **时间无 am/pm**，规则：小时 `11` → am；`12` → pm（中午）；`1–10` → pm。Film Forum 没有 11 点前的场次。写单测。
- 增强：每部片 GET 一次 `detail_url`，正文自由文本形如 `Japan, 1964 Directed by Masaki Kobayashi … Approx. 183 min.`，正则 `(\d{4})\s+Directed by ([^.<]+)` 和 `(\d+)\s*min`。按 URL 缓存，一次运行内不重复请求。
- `coming_soon` 暂不接入（没有场次）；以后可做「即将上映」侧栏。

**实测补充**：同一部片在不同天的标题可能一个被截断成 `…` 一个没有（"YOU HAD TO BE THERE: HOW THE TORONTO GODSPELL…" vs "YOU HAD TO BE THERE"），按 `detail_url` 统一成未截断的那个。首轮片详情页没有 "Japan, 1964" 这类行，只有 `DIRECTED BY NICK DAVIS`，所以首轮片通常只有导演。月份推断改为「取离抓取日最近的那个日期」，跨月 / 跨年都成立。

**实测补充（2026‑10‑06）**：首轮片详情页其实有一行大写的片目：`2026     355 MIN.     USA     IN RUSSIAN WITH ENGLISH SUBTITLES`（或 `… USA     GREENWICH ENTERTAINMENT`，即发行方）。年份取这一行开头的年份；片长匹配不分大小写（以前只认小写 `min`，首轮片的 `98 MIN.` 都漏了）；语言从「评论（Reviews）之前、160 字以内」的一行里用 `language_from_text` 读——以前完全没读，首轮的非英语片只能靠 TMDB，而《My Undesirable Friends: Part II – Exile: Chapters 1-3》这类分段放映的片名 TMDB 查不到。`language_from_text` 同时修了对全大写文字的处理（"RUSSIAN" → "Russian"，"…, AND ILOKANO" 拆开）。片名只有一部分大写时（"MY UNDESIRABLE FRIENDS: PART II – EXILE: Chapters 1-3"）按 `title_case_runs` 只转大写的那几段；`smart_title` 改为认任何文字的字母，"KANAŁ" / "KATYŃ" 不再变成 "KanaŁ"。

---

## 6. Metrograph — ★★ 服务端 HTML，单页含全部日期，**有 IP 限速**

```
GET https://metrograph.com/nyc/          # 主源；/calendar/ 会 301 到这里
GET https://metrograph.com/film/         # 备用视图，按片分组，同样服务端渲染
```
- 无日期参数；一页包含约 27 天（实测 2026‑09‑23 → 10‑19），已排片的天约 19 个。
- **限速**：站点在 WordPress.com Atomic 上，边缘缓存约 185s；任何缓存 MISS 的请求（带查询参数、`/wp-json/*`、影片详情页）都会触发按 IP 的 429，且一旦触发持续 15 分钟以上。探测时本机 IP 已被 429 过。
- 因此：**每次运行只 GET 一次 `/nyc/`，不带参数，不抓详情页，429 立即停止不重试。** 兜底 screenslate（nid 6）。

**单条**
```html
<div class="calendar-list-day movies-grid" id="calendar-list-day-2026-09-23">
 <div class="item film-thumbnail homepage-in-theater-movie">
  <a href="/film/?vista_film_id=9999000497" class="image"><img src="https://metrograph.imgix.net/..."/></a>
  <h4><a href="/film/?vista_film_id=9999000497" class="title">Happy Together</a></h4>
  <div class="film-metadata">Wong Kar-wai / 1997 / 96min / DCP</div>
  <div class="showtimes">
   <a href="https://t.metrograph.com/Ticketing/visSelectTickets.aspx?cinemacode=9999&txtSessionId=31018" title="Buy Tickets">2:00pm</a>
   <a href="...txtSessionId=31019">7:15pm</a>
  </div>
 </div>
</div>
```
未排片的天会有 `class="... unscheduled"`。

**解析**
- `div.calendar-list-day` 的 `id` 去掉 `calendar-list-day-` 前缀即日期。
- 每个 `div.item`：标题 `h4 a.title`；`div.film-metadata` 按 ` / ` 切分，字段顺序 director / year / runtime / format，但可能缺项（用正则分别识别 `^\d{4}$`、`^\d+min$`、format 集合，其余当导演）。
- `div.showtimes a` 每个一条，时间 `%I:%M%p`，`ticket_url = href`，`txtSessionId` 可作 id 的一部分。
- `detail_url = "https://metrograph.com" + href`。

**实测补充**：`div.film-description` 里有 "Q&A with … on Saturday, September 26th" 这类说明，是**按片**不是按场的；带具体日期的只挂到那一天的场次上（并去掉日期尾巴），不带日期的（"U.S. premiere"）挂到所有场次。售罄场次是 `<a class="sold_out" title="Sold Out">` 且没有 href。

---

## 7. L'Alliance New York（French Institute）— ★★ 服务端 HTML 卡片 + 详情页

```
GET https://lallianceny.org/events/?_event_categories=film
```
- 无日期参数、无分页，返回所有未来的 Film 类活动（当前 8 张卡，9 月中到 12 月）。
- WordPress + Bricks + WP Grid Builder；`wp-json/wp/v2/event` 开放但没有日期字段，不用。Cloudflare 放行 curl。

**列表卡片**
```html
<li class="brxe-lzzcps brxe-block event-card--list"><article class="event-card">
 <div class="event-card__header">
  <div class="event-card__category-block">Film</div>
  <span class="event-card__location-name">Florence Gould Theater</span>
 </div>
 <h3 class="event-card__heading">La Chienne</h3>
 <div class="brxe-psotcw brxe-code"><p>Tuesday, September 29, 2026   4:00 PM</p></div>
 <a class="event-card__buy-tickets" href="" target="_blank">Buy Tickets</a>      ← 列表页 href 为空
 <a class="event-card__learn-more-btn" href="https://lallianceny.org/event/la-chienne/">Learn More</a>
</article></li>
```
系列卡片的日期是区间：`Tuesday, September 15, 2026 - Thursday, October 15, 2026`。

**详情页**（`event-card__learn-more-btn` 的 href）
- `<h3>Schedule</h3>` 之后的 `div.brxe-code` 里是成对的 `<p>Saturday, October 31, 2026</p><div>11:30 AM</div>`，重复放映有多对。
- `div.event-card__details` 里有 `dirs. ..., France, 2015, DCP` 与 `Run Time: 84 min`。
- 真正的购票链接：`https://buytickets.at/lalliancenewyork/NNNN`。

**解析**
- 列表页：`li.event-card--list` → 标题、`screen = .event-card__location-name`、日期文本、详情 URL。
- 日期文本匹配 `^(.+?\d{4})\s+(\d{1,2}:\d{2} [AP]M)$` → 单场；否则视为系列 / 区间。
- **对每张卡都 GET 详情页**（只有几张，成本低），用 Schedule 段的 `<p>/<div>` 对生成所有场次（这样系列会展开成具体日期），并取 director / year / format / runtime / ticket_url。
- 用语义类名（`event-card__*`）而不是 `brxe-xxxxxx` 哈希类名做选择器。

**实测补充（与上文不同之处）**
- 列表卡片的日期文字**没有时间**（只有 `Tuesday, September 29, 2026`），所以必须抓详情页。
- 卡片标题和详情页 slug 不一定对应（"La Chienne" → `/event/the-remake/`），一律用卡片里的 learn‑more 链接。
- Schedule 块结构是 `<p>日期</p><div><div>4:00 PM</div><div>7:00 PM</div></div>`，一个日期下多个时间。
- 只有日期区间、没有时间的卡片（Godard 系列总页、Family Saturdays）是容器，跳过。
- 导演行是 `Dir. Jean Renoir, 1931, 93 min, DCP.`；双片连映有两行，导演合并。**不要用一个大正则去扫全文**（嵌套量词会灾难性回溯卡死），按行解析。h1 下面的副标题（"The Remake"）作为 series。

**实测补充（2026‑09‑30）**
- 只有日期区间的「系列总页」（如 Jean-Luc Godard: Unmade and Abandoned）没有自己的场次，但它的 `<h2>Events In This Series</h2>` 之后列出了包含的每一场（`a[href*="/event/"]`）。只取这个标题之后的链接，页面顶部导航菜单里的 `/event/` 链接要排除。据此给每一场设 `series` = 系列名，场次页自己的小标题（"The Remake"）改放 `note`。不需要额外请求，系列总页本来就会抓。
- 有的场次页不写 `Dir.`，片目写成 `(1981, 39 min, DCP)` / `, 1982, 11 min, DCP)`，从这里取格式（和单片时的年份）。
- 「Family Saturdays」系列里有几部儿童电影（Phantom Boy、Mary Anning、Les Choristes），它们不在「电影」分类的列表页里，目前没有抓。

**实测补充（2026‑09‑30，系列子页面）**
- 「Family Saturdays」的电影不在 Film 分类列表里，只作为系列总页「Events In This Series」下的成员出现，而且和工作坊、讲故事、木偶剧混在一起，分类标签完全相同（Family Saturdays, Kids）。做法是抓这些成员页（每次最多 15 页），页面主体里有导演片目行（`dir.` / `dirs.`）的才算电影。
- 子页面底部有「**Other** Events in This Series」列表，列着同系列其他影片的导演和片长，解析前必须在这里截断。
- 导演行会被排版拆成多行（`dirs. Jean-Loup` / `Felicioli` / `and Alain Gagnol, France, 2015, DCP`），要把文字拍平后再按「dir(s). … 年份 …」到句号为止匹配。国家可能写在年份后面（`2025, Switzerland/Belgium, DCP`），格式只认已知的格式词。

---

## 8. MoMA — ★★★ 需要浏览器（Cloudflare managed challenge）

- `https://www.moma.org/calendar/film` 及全站任何路径对 curl 一律 403 "Just a moment…"，换 UA、HTTP/1.1、Googlebot 都无效。`.json`、`Accept: application/json`、`.ics`、`/rss` 同样被挡。
- 页面本身是服务端渲染（Wayback 2025‑12 快照确认），拿到 HTML 后解析很简单。

**页面结构**（拿到 HTML 后）
- `/calendar/film` 只列 3 条「Upcoming showtimes」和系列入口；真正的全量在各系列页 `/calendar/film/<seriesId>`，以及 `/calendar/?happening_filter=Films&locale=en&location=both`（分页，参数格式未确认）。
- 系列页 / 首页里的单条：
```html
<h3>Tue, Dec 30</h3>
<li><a href="/calendar/events/11051">
  <p><span><em>BLKNWS: Terms &amp; Conditions</em>. 2025. Directed by Kahlil Joseph</span></p>
  <p><span>7:00&nbsp;p.m.</span></p>
  <p><span>Introduced by cinematographer Bradford Young</span></p>
  <p><span>MoMA, Floor&nbsp;T2/T1</span></p>
</a></li>
```
- 单场页 `/calendar/events/<id>` 有 JSON‑LD `@type: ScreeningEvent`，`startDate` 形如 `"2015-04-06T19:00"`（无时区，按纽约处理），`location.name` 是影厅，`superEvent` 是系列。这是最干净的结构化来源。

**策略**
1. Playwright（Chromium，持久 user‑data‑dir）打开 `/calendar/film`，等挑战通过；收集所有 `a[href^="/calendar/film/"]` 系列链接，逐个打开并解析 `<h3>` 日期 + `<li>` 行。标题行正则：`^<em>(.+?)</em>\.\s*(\d{4})?\.?\s*(?:Directed by (.+))?$`。
2. 时间 `7:00 p.m.` → 把 `p.m.`/`a.m.` 规范成 `PM`/`AM` 再 `%I:%M %p`。
3. 若挑战 30s 未通过 → 失败 → 兜底 screenslate（nid 81）。实际使用中 screenslate 对 MoMA 的覆盖是完整的，所以这条兜底很可靠。

**实测补充（2026‑09‑24）**
- headless Chromium（包括把 UA 改成普通 Chrome、复用 cookie）一直停在 "Just a moment…"。有窗口的 Chromium 第一次 0.7 秒就过了，但之后几次都被升级成更严格的挑战、30 秒过不去。**没有继续做绕过**（stealth 插件、自动点验证框都属于规避检测，不做）。
- 所以现在的实际路径是：浏览器（有窗口，`browser.headless: false`）试一次 → 失败 → screenslate。`primary_cooldown_h: 20` 让浏览器大约一天只试一次，其余运行直接走 screenslate（约 20 秒）。
- `networkidle` 在 MoMA 永远等不到（分析脚本一直有请求），用 `load` + 短暂等待。
- `moma.py` 的解析是按本节上面的 Wayback 结构写的，测试用的是**合成** fixture（`tests/fixtures/moma/synthetic_series.html`）。浏览器路径第一次真正成功时，`data/raw/<date>/moma*.html` 会存下真页面，届时用它替换 fixture 并核对解析。
- Playwright 版本锁在 1.62.0，对应本机已装的 `ms-playwright/chromium-1234`，不需要再下载浏览器。

---

## 9. Filmadelphia（Philadelphia Film Society）— ★★★★ 被 WAF 拦截

```
https://filmadelphia.org/showtimes/?start_date=9/24/2026    # 一天一页，M/D/YYYY 不补零
```
- SiteDistrict WAF：任何路径（含 `robots.txt`）对 curl 一律 403；浏览器 UA 会得到一个 JS 指纹挑战（检测 `navigator.webdriver`、鼠标轨迹、WebGL，POST 到 `/blockview?hash=…`）。桌面浏览器面板也被判为 "Bad Bot Request"。Wayback 自 2025‑04 起也被封。
- 页面结构（来自 2025‑04 的存档，理论上拿到 HTML 后可解析）：
```html
<div class="movie-tags theater--film-society-bourse cat--first-run">
  <div class="mb-5 text-xl font-bold"><a href="https://filmadelphia.org/movies/audreys-children/">AUDREY'S CHILDREN</a></div>
  <div><span>Theater:</span> Film Society Bourse</div>
  <div><span>Runtime:</span> 110 min</div>
  <div><span>Director:</span> AMI CANAAN MANN</div>
  <a class="button-showtime" href="https://prod5.agileticketing.net/websales/pages/ticketsearchcriteria.aspx?evtinfo=481066">3:45pm</a>
  <div>Release</div><div>2024</div>
```
  场次按钮在移动 / 桌面各渲染一份，按 `evtinfo` 去重；影厅从 `theater--film-society-{bourse|center|east}` 类名取。

**备选方案（按优先级）**
1. PFS 的售票系统是 Agile Ticketing，Agile 有开放的 `feed.ashx?guid=<GUID>&showslist=true&format=json`；探测到的 GUID 只有会员页的（返回空）。如果能在 PFS 或费城电影节页面里找到排片 feed 的 GUID，这是最稳的路。
2. 用真实 Chrome 手动打开一次 `filmadelphia.org` 通过挑战，导出 cookie 给 scraper 复用（cookie 有效期未知）。
3. Playwright + `playwright-stealth` 非 headless 模式——属于规避检测，不采用。

**现状（2026‑09‑27）：方案 1 成功，已启用。**
- 通过网页搜索找到 PFS 在 Agile 的公开入口 `entrypoint.aspx?GUID=6634566a-a49f-4dec-89e6-bb4c5eda4814`（"Philadelphia Film Society - EVENTS"），用同一个 GUID 调 feed：
  `GET https://prod5.agileticketing.net/websales/feed.ashx?guid=<GUID>&showslist=true&withmedia=false&format=json&v=latest`
  httpx 直接 200，无 WAF，约 850 KB，`UpdateFrequencyMinutes: 10`，覆盖三处影院（Film Center、Bourse、East）约 3 个月，首轮片的每日场次也完整。
- 结构：`ArrayOfShows[]`（一部片）→ `CurrentShowings[]`（一场）：`StartDate` / `EndDate`（本地时间，无时区）、`Venue.Name`（"PFS - Bourse Theater 3"）、`LegacyPurchaseLink`、`ContentDelivery`（只要 `InPerson`）、`DateTBD`。
- `CustomProperties[]` 是 Name/Value 对：`Director`、`Release Year`、`Run Time`、`Format`（"35MM"、"4K"）、`Film Series`、`Event Type` 等，全大写，统一过 `smart_title()`。系列名用 `Film Series`，没有时用 show 的 `Type`（排除 "First-Run" / "CURATED" / "Special Event"）。
- 标题里的 "w/ Q&A" 等拆到 note。
- Agile 的 `ticketsearchcriteria.aspx` 单场页面有 Incapsula WAF（curl 也被拦），但 feed 端点没有；不要抓单场页面。

**实测补充（2026‑10‑02，开放字幕）**：开放字幕场次在每一场的 `CustomProperties` 里有一个**隐藏**属性 `{"Group": "Accessibility", "Name": "Amenities", "Value": "Open Captioning"}`。实测只出现在周二、Bourse 和 East 的首轮片场次上；同一天 Film Center 的回顾展场次没有。按这个标记（而不是按星期几）给场次加备注「Open captions」，网页的「有字幕」筛选把它们算进去。解析在通用的 `scraper/adapters/agile.py` 里，其他 Agile 影院同样适用。

---

## 10. screenslate.com 兜底源 — ★ 开放 JSON（Drupal 10 JSON:API + 自定义 REST）

screenslate 收录了这里全部 8 家纽约影院（包括 L'Alliance），只是更新慢。它的 API 完全开放、无鉴权：

```
# 某天某影院的所有场次（date=YYYYMMDD；NYC city id 10969）
GET https://www.screenslate.com/api/screenings/date?_format=json&date=20260924&field_venue_target_id=6
→ [{"nid":"12345","field_time":"7:00pm","field_note":"Q&A ...","field_timestamp":"1758758400"}, ...]

# 批量取场次详情（nid 用 + 连接）
GET https://www.screenslate.com/api/screenings/id/12345+12346?_format=json
→ [{"title":"...","field_display_title":"...","venue_title":"<a href=...>Metrograph</a>",
    "field_series":"<a ...>Series</a>","field_url":"https://ticket-link",
    "media_title_labels":"Happy Together","media_title_info":"Wong Kar-wai|1997|96M",
    "media_title_format":"DCP","field_on_film":"0","body":"..."}]

# 影院 nid 查询
GET https://www.screenslate.com/jsonapi/node/venue?fields[node--venue]=title,path&page[limit]=50
```

已确认的 nid：Metrograph 6、Film Forum 13、L'Alliance 7、MoMA 81、BAM 244、Anthology 327、Japan Society 339、Film at Lincoln Center 355。

**解析**
- 对每个 `venue_id` 的每一天（today → horizon）调 `date` 端点，再把 nid 合并成一次 `id` 请求。
- `field_timestamp` 是 Unix 秒 → `start`。`venue_title` / `field_series` 是 HTML 片段，用 bs4 取文本。
- 多片节目：`media_title_labels` 用 `|` 分隔，`media_title_info` 同序，合并成 `title = "A + B"`。
- `field_on_film == "1"` 时 format 一定是胶片。
- 输出的 Screening `source = "screenslate"`。

**数据模型参考**：screenslate 的 screening = (venue, series?, [media_title + format]*, [showtime]*)，即「一个节目对应多部片、多场次」。我们的 `Screening` 是扁平的「一场次一行」，更适合时间轴渲染；他们的 formats 词表（DCP、35mm、16mm、70mm、VHS、Digital Video、Blu‑ray、DVD…）可直接拿来做 `format` 规范化。

**值得抄的 UX**：默认今天；前一天 / 后一天 + 日期选择器，URL `/listings/YYYY-MM-DD`；「On Film」和「Upcoming（隐藏已开场）」两个开关；按影院分组、影院按最早场次排序、场次带脚注备注。

**实测补充（与上文不同之处，2026‑09‑24）**
- **Python 的 TLS 握手（httpx / urllib）一律 403**，换 UA / 头都没用；系统 `curl` 正常 200。所以 screenslate 走 `HttpClient` 的 `transport="curl"`（其他源仍用 httpx）。偶尔也会返回空 body，按空列表处理。
- `field_timestamp` 现在是**本地时间 ISO 字符串**（`"2026-09-26T12:15:00"`），不是 Unix 秒；两种都兼容。
- `media_title_labels` / `media_title_info` 是 **HTML `<span>`**，多片之间用 `|` 分隔；每片的 info 是 `<span>导演</span><span>年份</span><span>96M</span><span>格式</span>`，任一项可能缺失。
- `field_on_film` 是 `"true"` / `"false"`，不是 `"1"`。胶片但格式未知时 `format = "Film"`（前端「只看胶片」认它）。
- 标题：优先 `field_display_title`（"New York No Story"）；否则 1 部用片名，2–3 部用 ` + ` 连接，更多用 "A + B + N more"（短片合集常有 8–17 部）。内部 `title` 字段是编辑的备注（"matrix moma"），只作最后兜底。
- 覆盖明显不如主源：同一天 Metrograph 主源 149 场，screenslate 只有 71 场。

---

## 11. Bryn Mawr Film Institute — ★★ 服务端 HTML（本周页 + 影片页）

2026‑10‑06 实测。WordPress 站（`brynmawrfilm.org`），售票是 Agile Ticketing（`shop.brynmawrfilm.org`）。网页里能看到的 GUID `4ce679c9-…` 只出现在购物车 / 登录链接里，喂给 feed 只返回空壳（和 IFC 等一样，PLATFORMS.md §3），所以读网站本身。

```
GET https://brynmawrfilm.org/films/week/        # 今天起约 8 天
<h5>Today · Tuesday, October 6</h5>
<b><a href="https://brynmawrfilm.org/event/primetime/">PRIMETIME</a></b>  (R) USA – 1 hr 50 min  <span class="icon icon-4k"></span><br>
<span class="showtime-past">1.00 Open Caption</span> <a href="https://shop.brynmawrfilm.org/websales/pages/ticketsearchcriteria.aspx?evtinfo=582090~…" class="showtime">4.15</a> …

GET https://brynmawrfilm.org/films/?view=list   # 全部节目，只有日期：<td><nobr>Oct 6 – 15</nobr></td><td><b><a href="/event/…">TITLE</a></b> (R) · USA – 1 hr 50 min</td>
GET https://brynmawrfilm.org/event/<slug>/      # 单个节目：片名 <h2>TITLE<div class="subtitle">On 35mm</div></h2>，
                                                # "1961 · d. John Huston"、系列链接 /series/…、标签 div.tags，
                                                # div.buy-tickets 里 <b>Tuesday, October 13</b> 加当天的 a.showtime
```

- **时间没有上午 / 下午**："1.00"、"4.15"、"7.30"；上午场网站自己会写 "11.00am"。所以没写的一律按下午（12 点 = 中午）。时间后面的字是那一场的备注："Open Caption"（开放字幕，计入「有字幕」）、"SF"（Sensory Friendly 感官友好场）。
- "– with subtitles" 记为备注 "Subtitled"（计入「有字幕」）；副标题 / 标签里的 35mm、16mm、70mm 记为规格。片名全大写，按「连续两个以上全大写词或一个长词」转换大小写，"THE HEIRESS with Karina Longworth" → "The Heiress with Karina Longworth"。
- 日期都不带年份，按页面抓取日推断（`nearest_date`）。
- 列表里带 "Instructor:" 的是课程 / 研讨课（Cinema Classics Seminar 等），不是放映，跳过；对应影片另有自己的条目。
- **抓取**：本周页 + 列表页，再对「本周页之后还有场次、且在 `horizon_days` 内」的节目各取一次影片页（按日期由近到远，最多 30 页，每次实时取，因为要读的是时间）；本周页已覆盖的日期不再从影片页取。只在本周页出现的片，导演 / 年份用影片页补（`enrich`，按 7 天缓存）。每次运行约 32 个请求、间隔 2 秒。
- 4 个影厅不在网页上写，`screen` 为空。地址：824 W Lancaster Ave, Bryn Mawr, PA 19010。

---

## 12. Hiway / County / Ambler Theater（Renew Theaters 的网站模板）— ★★ 服务端 HTML

2026‑10‑06 实测。`hiwaytheater.org` 是 Renew Theaters（同一家非营利机构还经营 County Theater、Ambler Theater）的 PHP 模板，图片来自 `renewtheaters.org`；售票是 INDY（`tickets.hiwaytheater.org`，前端应用，数据走它自己的 GraphQL）。网站本身已经有全部场次和购票链接，不去读售票系统。

```
GET https://www.hiwaytheater.org/            # Now Playing：本周正片的全部场次（另含几场特别放映）
GET https://www.hiwaytheater.org/specials    # 全部特别放映，排到两三个月后（/events 302 到这里）
<div id="box-times">
  <div class="details"><div class="year">1981</div><div class="format">35mm</div></div>
  <div class="header"><span class="tag-bar cult">Cult Cinema Club</span><div class="subheader">…</div>
    <a href="films/halloween-ii" class="title">Halloween II</a>
    <div class="date-container" data-date="Fri Oct 23">           # 首页是 "Tue 6"（只有星期和日）
      <ul class="session-times"><li><a href="https://tickets.hiwaytheater.org/checkout/showing/halloween-ii/3821019">
        9:45 PM <span class="screen-attribute">OC</span></a>
```

- 正片时间不写上午 / 下午（"7:00"），特别放映多数写（"10:00 AM"）；没写的按 Film Forum 的规则：11 点 = 上午，12 = 中午，1–10 = 下午。
- "OC" = 开放字幕场（记为备注 "Open caption"，计入「有字幕」）。`tag-bar` 是系列（"Ends Thu Oct 8" 这类排期提示除外），`subheader` 记为备注（"A Christmas Carol (1951)"），`.format` 是规格。
- 首页日期 "Tue 6" 没有月份：在抓取日附近找「6 号且是星期二」的那天；/specials 的 "Sat Oct 10" 按 `nearest_date`。
- 正片每周一 / 二才排下一周，所以首页就是正片的全部；Coming Attractions 页只有片名、没有时间，不读。
- 模块 `renew` 带 `base_url` 参数，三家共用，每家每次 2 个请求：Hiway（`hiwaytheater.org`，212 Old York Rd, Jenkintown）、County Theater（`countytheater.org`，20 E State St, Doylestown）、Ambler Theater（`amblertheater.org`，108 E Butler Ave, Ambler）；地址取自各站页脚的 Apple 地图链接。2026‑10‑06 三站所有未标上午 / 下午的时间都在 12:50–8:30 之间，规则没有歧义。

---

## 13. Coolidge Corner Theatre（波士顿 Brookline）— ★★ 服务端 HTML，每天一页（配方）

2026‑10‑06 实测。Drupal 站；售票是 Agile（`store.coolidge.org`），网页里可见的 GUID 喂 feed 只返回空壳（PLATFORMS.md §3），所以读网站。

```
GET https://coolidge.org/showtimes?date=2026-10-08      # /films-events/now-playing?date=… 302 到这里
<div class="now-playing-page-1"> … <div class="film-card">
  <a class="film-program__link …" href="/programs/prints-darkness"><span class="film-program__title">Prints of Darkness</span></a>
  <a class="film-program__link film-type__link--35mm" href="/type/35mm-screenings"><span class="film-program__title">35mm</span></a>
  <h2><a class="film-card__link" href="/films/rosemarys-baby">Rosemary’s Baby</a></h2>
  <div class="film-card__runtime">2hrs 17mins</div>
  <a href="https://store.coolidge.org/websales/pages/ticketsearchcriteria.aspx?evtinfo=…" class="showtime-ticket__button">
    <span class="showtime-ticket__time">7:30pm</span><span class="showtime-ticket__venue">MH2</span></a>
```

- 时间带 am / pm，日期来自网址，所以是配方（`scraper/recipes/coolidge-corner-theatre.yaml`）：`daily` 翻 21 天，每天一个请求。午夜场写成 11:59pm，照写。
- `film-program__link` 是系列（`film-type__link--*` 是类型标签，只取 35mm / 70mm / 16mm 作规格）；`MH1`–`MH6` 是影厅，`ECEC` 是教育中心。带 `/programs/coolidge-education` 标签的是课程 / 研讨课 / Open Screen，不是放映，item 选择器里用 `:not(:has(…))` 排除。
- 户外场（"… Aboard the Sea Witch" 在 Quincy 的 USS Salem 军舰上；"Coolidge at the Speedway" 在 Brighton 的 Charles River Speedway，525 Western Ave）没有影厅名：`venues.yaml` 的 `location.places` 对没有 `screen` 的场次按系列 / 片名匹配，加入日历时地址才对。
- 片长 "2hrs 17mins" 配方算不了（不能把小时换成分钟），交给 TMDB；新片的周排期一般只排到一两周后，特别放映更远，21 天是请求数和覆盖面的折中。

---

## 14. Harvard Film Archive（波士顿 Cambridge）— ★★ 服务端 HTML（配方）

2026‑10‑06 实测。`/calendar` 每页约四周，"View more" 是 `/calendar?page=2`、`?page=3`；季度节目一般排到两个半月后，三页覆盖全部（第 3 页没有下一页链接）。以后排得更远时在配方里加 `?page=4`。

```
<div class="m-calendar__spot--event event">
  <a href="/calendar/the-third-man-2026-09" class="event__link">…</a>
  <div class="event__series">The Cold Heart is More Precious than Diamonds. ...</div>
  <div class="event__time"><time datetime="2026-10-19 19:00:00"><span>7:00 pm</span></time></div>
  <h5 class="event__title">The Third Man</h5>
  <div class="event__info">Directed by Carol Reed,  1949</div>
  <div class="event__labels"><i class="label label--blue"><span class="tooltip">New 35mm print</span></i> …
```

- 每场自带完整的开始时间（`time[datetime]`），配方用 `date: {kind: attr}`，不用推断日期。
- 蓝色标签是规格："New 35mm print" → 35mm，"Screening on Film" → Film（胶片、规格未知，计入「只看胶片」），"Screening on 35mm / DCP" 不确定，不填。其他标签（现场配乐、导演到场、票价）记为备注。
- 系列名太长时网站截成 "…, ..."：配方去掉省略号和结尾的标点，保留能读的部分；完整名字在页面底部的 "Current Programs"，配方表达不了对照，就不取。
- 没有在线购票链接（票在影院售票处卖），`detail_url` 是活动页。地址：Carpenter Center，24 Quincy St, Cambridge。

---

## 15. Somerville Theatre（波士顿 Somerville）— ★ 同站公开 XML（TAPOS 售票 feed）

2026‑10‑06 实测。WordPress 站。`/calendar` 是服务端渲染的重映日历，`/schedule`（正片）没有场次 HTML，由 `showtime-select.min.js` 在浏览器里取：

```
GET https://www.somervilletheatre.com/wp-admin/admin-ajax.php?action=tapos_feed      # application/xml，约 340 KB
<Feed><Films><Film><Code>163</Code><FilmTitle>Aliens 70mm</FilmTitle><ShortFilmTitle>Aliens</ShortFilmTitle>
      <RunningTime>137</RunningTime><IMDBCode>tt0090605</IMDBCode><Directors>James Cameron</Directors>…</Film>…
<Performance><FilmCode>163</FilmCode><PerformDate>2026-11-18</PerformDate><StartTime>19:00:00</StartTime>
      <Screen>Main Theatre - Somerville</Screen><PerfFlagsDescription>70mm</PerfFlagsDescription>
      <BookingURL>https://internet-ticketing.com/websales/sales/CSBSOM/book?perfcode=1186</BookingURL>
      <SoldOutLevel>N</SoldOutLevel><PerformancesHidden>N</PerformancesHidden>…</Performance>
```

- 一次请求就是全部：正片和重映（35mm / 70mm）都在，排到一个多月后。这是影院自己网站给浏览器的公开接口，和 Landmark 读 Webedia 接口同理。
- 片名用 `FilmTitle`（`ShortFilmTitle` 截到 20 个字），去掉结尾的规格（"Aliens 70mm" → "Aliens"，规格 70mm）。场次标记 `PerfFlagsDescription`：35mm / 70mm / 4K 是规格，"Open Captions" 是开放字幕备注。`SoldOutLevel` 不是 N 时记 Sold out；`PerformancesHidden` / `Virtual` 为 Y 的跳过。影片页按网站脚本的规则拼：`/production/<FilmTitle 的 slug>/`。
- **`Directors` 不可信**：混进了别的片的人（"The Blues Brothers: Derek Drymon|John Landis"、1925 年 "The Phantom of the Opera: Johannes Roberts|Norman Jewison"），所以不用。改用 `IMDBCode`：`Screening.imdb_id` → TMDB `/find/{imdb_id}`，一部片一个确定的匹配，导演、年份、片长、语言都从那里来（`language.by_imdb`，缓存键 `imdb:<id>`）。没有 IMDb 号的片照常按片名查。
- `/calendar`（重映日历）和 `/events`（音乐会、现场活动）不读：前者的场次都在 feed 里，后者不是电影。地址：55 Davis Square, Somerville。

---

## 16. Paris Theater（纽约）— screenslate + 官网首页的特别活动

2026‑10‑07 实测。Netflix 经营的单厅影院。官网（`paristheaternyc.com`，Next.js）只有影片介绍和特别活动；常规场次在售票站 `tickets.paristheaternyc.com`，对程序返回 Cloudflare 拦截页（403），**不绕过**。

- 常规场次读 screenslate（nid 43542），它只排到几天之后。
- 官网首页的 RSC 数据（`self.__next_f.push([1,"…"])` 里的 JSON 字符串）带着几周后的特别活动：`{"EventName":"LA BOLA NEGRA | Sneak Preview + Q&A …","EventDate":"2026-10-15","TicketLink":"https://tickets.paristheaternyc.com/order/showtimes/2001-3093/seats","EventTime":"7:05 PM"}`。活动名是大写、不带年份；同一份数据里有影片记录 `{"FilmName":"A Place in the Sun","Slug":"a-place-in-the-sun-paris","Director":"George Stevens",…,"Year":"1951"}`，用它补片名写法、导演、年份和影片页（`/film/<slug>`）——没有年份时 TMDB 会配成 2024 年的同名丹麦片。
- 合并：screenslate 也列出的活动（开场相差 10 分钟内、同一部片）只补备注和购票链接，其余追加。所有场次算这家影院的主源（不显示 "via screenslate"）。模块 `scraper/sources/paris.py`，每次约 30 个 screenslate 请求加 1 个首页请求。地址：4 W 58th St。


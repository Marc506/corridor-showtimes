# 影院平台适配器实测手册

> 2026‑09‑28 用 curl（桌面 Chrome UA）实测。`SOURCES.md` 记录的是「某一家影院」怎么抓；本文件记录的是「某一类平台」怎么抓——同一平台上的任何影院都能用同一个适配器，只需在 `venues.yaml` 里填参数，不写代码。配套设计见 `ARCHITECTURE.md` §5.7。
>
> 原始样本在 `tests/fixtures/platforms/<adapter>/`（说明见该目录的 README）。

## 0. 结论先行：28 家美国艺术影院的平台分布

对 28 家有代表性的美国艺术 / 重映影院做了探测（纽约 9、波士顿 3、芝加哥 2、洛杉矶 4、旧金山 2、其他 8）：

| 类别 | 家数 | 影院 | 适配器 |
|---|---|---|---|
| Filmbot（WordPress「Nightjar」主题） | 4 | Nitehawk、Brattle、Vidiots、Brain Dead Studios | `filmbot` ★ 最干净的 JSON |
| Veezi 售票页 | 3 | Roxy Cinema NYC、New Beverly、Roxie SF | `veezi` |
| Agile Ticketing | 4 (+PFS) | IFC Center、Coolidge Corner、Gene Siskel、Belcourt | `agile`，**但 feed GUID 不在网页里**，需影院提供或人工查找；网页本身是服务端渲染，可走 `recipe` |
| 自家公开 JSON | 3 | Alamo Drafthouse（全国）、Trylon（WP My Calendar）、Paris Theater（Next.js RSC 内嵌） | `alamo`、`wp-my-calendar`；Paris 走 `recipe`/custom |
| Wix Events（HTML 内嵌 JSON） | 1 | Lightbox Film Center | `wix`（§14） |
| Tessitura TNEW | 2 | BAMPFA（服务端 HTML）、Jacob Burns（纯 JS） | 无公开 JSON；BAMPFA 走 `recipe` |
| Eventive | 1 | Northwest Film Forum | `eventive`（需站点内嵌的公开 key） |
| 服务端 HTML、各写各的 | ~6 | Quad、Harvard Film Archive、Austin Film Society、Spectacle、Light Industry、（以及上面 Agile 的 4 家） | `recipe`（声明式配方） |
| 纯 JS、无易得端点 | 2 | American Cinematheque、Jacob Burns | `recipe` + `render: browser`，或 custom |
| 被防火墙挡住 | 4 | Museum of the Moving Image、Hollywood Theatre（Cloudflare）、Music Box、Cleveland Cinematheque（Sucuri） | 不可自动化；纽约的可用 screenslate 兜底 |

另外在这 28 家之外验证到的平台用户：The Events Calendar（UnionDocs）、Squarespace（Maysles Documentary Center）、Spektrix（英国 Tyneside Cinema；美国暂未发现电影院用户）。

**含义**：平台适配器只能零代码覆盖约 40%；另有约 35% 是「服务端渲染但结构各异」的 HTML，这一层要靠声明式配方（可由 LLM / Agent 生成）来吃掉；剩下约 20% 要么纯 JS、要么被挡，需要浏览器或放弃。所以 v2 架构是三层：**平台适配器 → HTML 配方 → 自定义代码**，外加「无法自动化」的明确判定。

---

## 1. Filmbot（Nightjar WordPress 主题）— ★ JSON

**识别**：HTML 含 `filmbot`（如 `filmbot-hall` 脚本）或 `wp-json/nj/v1`；确认方式是直接探测端点。

**端点**
```
GET <site>/wp-json/nj/v1/showtime/listings
```
多分店站点把分店放在路径里（Nitehawk：`https://nitehawkcinema.com/williamsburg/wp-json/nj/v1/showtime/listings`）。

**结构**
```json
{"movies":   [{"movie_id": 123, "movie_name": "Creepshow", "runtime": 95, ...}],
 "showtimes": [{"movie_id": 123, "datetime": "20260928180000", "purchase_url": "https://.../purchase/4672309/"}]}
```
`datetime` 是影院本地时间的 `YYYYMMDDHHMMSS`，无时区，用影院的 `timezone` 解释。

**补充**：这些站点的影片页和首页都带 JSON‑LD `ScreeningEvent`，`startDate` 是完整 ISO（含偏移）——可作交叉校验或备用（见 §8）。

**参数**：`base_url`。

---

## 2. Veezi 售票页 — ★★ 服务端 HTML + JSON‑LD

**识别**：网页里有 `ticketing.(us|uswest|useast).veezi.com/sessions/?siteToken=<26 位小写字母数字>`。正则 `siteToken=([a-z0-9]{26})`；host 三个区域实测互通，但按网页里出现的那个存。

**端点**
```
GET https://ticketing.<region>.veezi.com/sessions/?siteToken=<token>
```
无 JSON / ICS 变体（`?format=json`、`/api/sessions` 等都 404）。官方 API 需要影院签发的 `VeeziAccessToken`，不可用。

**结构**：页面同时含两个视图与一段 JSON‑LD，**优先解析 JSON‑LD**：
```json
[{"@type": "VisualArtsEvent", "name": "Kaboom",
  "startDate": "2026-09-28T18:45:00-04:00", "duration": "PT1H31M",
  "location": {"name": "Roxy Cinema", "address": {...}},
  "url": "https://ticketing.uswest.veezi.com/purchase/5781?siteToken=..."}]
```
HTML 备用路径：`#sessionsByFilmConent div.film#ST<id>` → `h3.title`、`p.film-desc`（导演 / "2020, 94 min, DCP" 自由文本）、`div.date-container h4.date` + `ul.session-times li a time`（"9:15 PM"）；`li.sold-out-session` 表示售罄。HTML 里日期无年份，JSON‑LD 有。

**范围**：滚动窗口约 1 个月。

**参数**：`site_token`，`region`（默认 `us`）。

---

## 3. Agile Ticketing — ★ JSON（需要 feed GUID）

**端点**
```
GET https://prod<N>.agileticketing.net/websales/feed.ashx?guid=<GUID>&showslist=true&withmedia=false&format=json&v=latest
```
- `N` ∈ 1–6，成对集群（PFS 在 prod5/6，Coral Gables 在 prod3/4，Amherst 在 prod1/2）。错集群返回 HTTP 200 的 `SessionTimeout.htm` **HTML**，必须检查 `Content-Type: application/json`。适配器探测时按 1–6 轮询一次，记住命中的 host。
- `format=xml` 也可；无 ICS。
- 官方说明（agiletix.com/api）：feed 面向第三方站点公开；数据每 10 分钟刷新；要求服务端缓存；有未公布的用量限制；**未知 GUID 会触发 Incapsula 挑战**，所以探测要克制。

**结构**（PFS 实测，93 shows）
```json
{"LastUpdated": "2026-09-28T12:00:48", "UpdateFrequencyMinutes": 10,
 "ArrayOfShows": [{
   "ID": 656234, "Name": "A BUCKET OF BLOOD", "Duration": "66", "InfoLink": "...", "Folder": "Film Center Curated",
   "CustomProperties": [{"Name": "Release Year", "Value": "1952"}, {"Name": "Director", "Value": "..."},
                        {"Name": "Format", "Value": "DCP"}, {"Name": "Original Language", "Value": "English"}],
   "CurrentShowings": [{"ID": 658759, "DateTBD": false, "StartDate": "2026-10-03T17:30:00", "EndDate": "2026-10-03T18:36:00",
      "ContentDelivery": "InPerson", "SalesState": "DuringSales",
      "LegacyPurchaseLink": "https://prod5.agileticketing.net/websales/pages/ticketsearchcriteria.aspx?evtinfo=658759~...",
      "Venue": {"Name": "PFC - Greenfield", "City": "Philadelphia", "State": "PA"}}]}]}
```
日期是本地时间无偏移。现有 `scraper/sources/filmadelphia.py` 已经是这个 feed 的完整解析器，v2 把它泛化成 `agile` 适配器即可。

**GUID 怎么来（关键坑）**：
- 网页购票链接里的 `evtinfo=<id>~<guid>` **不是** feed GUID。
- 部分影院站点链到 `websales/pages/list.aspx?epguid=<GUID>`，这个「入口 GUID」可以直接喂给 feed（Coral Gables 验证成功）。但入口不是「节目列表」类型时（如捐赠页），feed 返回 0 条。
- 实测 IFC、Coolidge、Siskel、Belcourt 网页里可见的 GUID 喂 feed 都只返回空壳。它们的 feed GUID 要影院从 Agile 后台拿（Agile 支持文档 "Getting a GUID"）。
- 所以 `agile` 适配器的探测逻辑：找到 `epguid` → 轮询 prod1–6 → 有 shows 就成功；否则降级为 `recipe`（这 4 家网页都是服务端渲染），并在向导里提示「如果你能从影院拿到 Agile feed GUID，填进去效果最好」。

**参数**：`guid`，`host`（自动探测后固化）。

---

## 4. WordPress The Events Calendar（Tribe）— ★ JSON + ICS

**识别**：探测 `<site>/wp-json/tribe/events/v1/events?per_page=1`，必须返回 `application/json` 且含 `events` 键（有些站返回 200 的 HTML；Jacob Burns 返回 401）。

**端点**
```
GET <site>/wp-json/tribe/events/v1/events?per_page=50&start_date=YYYY-MM-DD
```
分页用响应里的 `next_rest_url`。ICS 版：`<site>/events/?ical=1`（`text/calendar`）。

**结构**（UnionDocs 实测）
```json
{"events": [{"id": 165691, "title": "Fall of Freedom &#8212; ...", "url": "https://uniondocs.org/event/...",
  "start_date": "2026-10-01 19:30:00", "end_date": "2026-10-01 19:30:00", "utc_start_date": "2026-10-01 23:30:00",
  "timezone": "America/New_York", "all_day": false, "cost": "&#036;10.00",
  "venue": {"venue": "UnionDocs, 352 Onderdonk Avenue", "city": "Ridgewood"},
  "categories": [{"name": "Screenings &amp; Events", "slug": "screenings-events"}]}],
 "total": 5, "total_pages": 1, "next_rest_url": null}
```
标题 / 费用是 HTML 实体编码，要 `html.unescape`。`timezone` 字段可直接用。可选参数 `categories`（slug 列表）用于只保留放映类活动。

**参数**：`base_url`，`categories`（可选）。

---

## 5. Squarespace — ★ JSON

**识别**：HTML 含 `Static.SQUARESPACE_CONTEXT`。活动集合要自己找：读 `/sitemap.xml`，找形如 `/<collection>/<slug>` 的路径，对候选 `/<collection>?format=json` 检查 `collection.typeName == "events"`。

**端点**
```
GET <site>/<events-collection>?format=json            # 当月
GET <site>/<events-collection>?format=json&month=october-2026&view=calendar   # 翻月，路径来自 pagination.nextPageUrl
```

**结构**（Maysles Documentary Center 实测）
```json
{"collection": {"typeName": "events"},
 "items": [{"title": "A HOME WORTH FIGHTING FOR", "startDate": 1790722800452, "endDate": 1790731800452,
            "fullUrl": "/calendar/a-home-worth-fighting-for", "excerpt": "",
            "location": {"addressTitle": "Maysles Documentary Center"}, "body": "<html...>"}],
 "pagination": {"nextPageUrl": "?month=october-2026&view=calendar"}}
```
`startDate` 是 epoch 毫秒（UTC）。

**参数**：`base_url`，`collection`（自动探测后固化）。

---

## 6. Eventive — ★ JSON（需站点内嵌的公开 key，灰色地带）

**识别**：网页链到 `<slug>.eventive.org`。该站是 JS 应用，其 `<script data-type="tenant">` 指向的 bundle 里含 `"event_bucket":"<24 hex>"` 与 `"api_key":"<32 hex>"`。

**端点**
```
GET https://api.eventive.org/event_buckets/<bucket>/events      # header: x-api-key: <tenant key>
GET https://api.eventive.org/event_buckets/<bucket>/films
```
无 key 返回 400 `An API key or token must be specified`。

**结构**（Cornell Cinema 实测）
```json
{"events": [{"id": "6a70d8c9...", "name": "Thelma & Louise", "start_time": "2026-08-17T23:30:00.000Z",
  "end_time": "2026-08-18T01:30:00.000Z", "timezone": "America/New_York",
  "venue": {"name": "Willard Straight Hall Theatre"}, "films": [{"name": "...", "credits": "...", "details": "..."}],
  "is_virtual": false}]}
```

**注意**：key 是租户随浏览器公开分发的，但 Eventive 文档称 API 文档「按需提供」。适配器只在 key 出现在影院自己的公开页面时使用，并在 README 写明；不做任何 key 猜测。

**参数**：`bucket`，`api_key`（探测时从 bundle 抽取），`site`（`<slug>.eventive.org` 的 slug，用于生成场次链接）。

**探测注意**：样本 `nwff_calendar.html`（NWFF 官网日历页）本身没有任何指向 `*.eventive.org` 的链接，探测器在这一页上认不出 Eventive；用户需要直接给 `https://<slug>.eventive.org/` 或含该链接的影片页。

---

## 7. Spektrix — ★ JSON（美国电影院暂未发现用户，先低优先级）

**识别**：链接 `system.spektrix.com/<client>/...`。

**端点**（无需鉴权，官方「Web User mode」）
```
GET https://system.spektrix.com/<client>/api/v3/events?instanceStart_from=2026-09-28T00:00&instanceStart_to=2026-11-28T00:00
GET https://system.spektrix.com/<client>/api/v3/events/<id>/instances
```
`events[]`：`id, name, duration(min), firstInstanceDateTime, attribute_Director, attribute_Certificate, isOnSale`；`instances[]`：`id, start ("2026-08-21T15:10:00" 本地), startUtc, isOnSale, cancelled, attribute_35mmScreening`。批量 `/api/v3/instances` 端点两次超时，未验证。

**参数**：`client`。

---

## 8. JSON‑LD `ScreeningEvent` / `Event` — ★ 通用兜底（需逐站验证）

**识别**：页面里 `<script type="application/ld+json">` 含 `@type` 为 `ScreeningEvent`、`Event`、`VisualArtsEvent` 且 `startDate` 非空的对象（可在 `@graph` 数组里）。

**读取字段**：`name`、`startDate`、`endDate`、`location.name`、`url`、`offers[].url / price`、`workPresented{name, director, duration}`、`eventStatus`。

**验证过的正例**：Brattle / Vidiots（Filmbot 站）首页与影片页；BAM 影片页（`@graph` 里每场一个 `Event`）；Veezi 售票页（`VisualArtsEvent`）。**反例**：Film Forum 首页的 `ScreeningEvent` 全部 `startDate: ""`——必须校验非空且可解析。

**范围**：通常只有当前页列出的场次；作为「首页 + 若干链接页」的抓取策略时要配 `pages` 列表。适合作为探测阶段的快速信号和小站的兜底。

**参数**：`pages`（URL 列表或 `follow: "a[href*=/movies/]"` 之类的一跳规则）。

---

## 9. ICS / iCal — ★ 通用

**识别**：`<link rel="alternate" type="text/calendar">`、`.ics` / `webcal://` 链接、TEC 站点的 `/events/?ical=1`。

**结构**
```
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261001T193000
DTEND;TZID=America/New_York:20261001T193000
SUMMARY:Fall of Freedom — Under Pressure...
URL:https://uniondocs.org/event/...
LOCATION:UnionDocs\, 352 Onderdonk Avenue
CATEGORIES:Screenings & Events
END:VEVENT
```
在 ~50 个站里只在 TEC 站发现了带场次的 ICS；Agile / Veezi / Squarespace 都不提供整表 ICS。优先级低，但实现成本极低（`icalendar` 库）。

**参数**：`url`。

---

## 10. 站点专属但公开的 JSON（值得单独做小适配器）

| 适配器 | 端点 | 结构要点 |
|---|---|---|
| `alamo` | `https://drafthouse.com/s/mother/v2/schedule/market/<market>`（`nyc` 等） | `data.sessions[]{cinemaId, sessionId, presentationSlug, showTimeClt, showTimeUtc, status}` + `data.presentations[]`（片名、时长）；一个 market 含多家门店，用 `cinemaId` 拆成多个 venue 或用 `screen` 区分。891 场，无鉴权 |
| `wp-my-calendar` | `<site>/wp-json/my-calendar/v1/events` | `{"2026-09-28": [{"event_title", "occur_begin": "2026-09-28 19:00:00", "event_link"}]}`，按日分组（Trylon） |

Paris Theater 的 Next.js RSC 内嵌 JSON（`self.__next_f` 里 `{"EventDate":"2026-10-15","EventTime":"7:05 PM","TicketLink":...}`）是站点专属，交给 `recipe` 或 custom；Lightbox 的 Wix 预热 JSON 是 Wix Events 的通用结构，见 §14 的 `wix` 适配器。

---

## 11. 服务端 HTML 各写各的：配方（recipe）适配器要覆盖的形态

从探测到的站点归纳出四种「日期在哪里」的形态，配方语法必须都能表达：

| 形态 | 例子 | 配方里的表达 |
|---|---|---|
| 日期标题 + 下面一串条目 | Anthology（`h3.current-day`）、Veezi HTML、MoMA | `date: {kind: heading, selector, format}` |
| 每张卡片自带日期属性 / 文本 | Roxy（`data-datetime="2026-09-28 21:30:00 -0400"`）、Siskel（`<time datetime>`）、L'Alliance | `date: {kind: attr, selector, attr, format}` |
| 日期只在 URL 参数里，一页一天 | Filmadelphia 官网、BAM 日历 | `pages: {kind: daily, url: "...?date={date:%-m/%-d/%Y}", days: 14}` + `date: {kind: page}` |
| 一页含全部日期、按块分 | Metrograph（`div#calendar-list-day-2026-09-23`）、Film Forum（tab + 注释） | `date: {kind: container, selector, attr: id, regex: "(\\d{4}-\\d{2}-\\d{2})"}`；Film Forum 的注释 + 无 am/pm 仍留给 custom |

时间形态：`7:00pm` / `7:00 PM` / `7 PM` / `19:00` / 无 am/pm（Film Forum，仅 custom）。配方里 `times.regex` 默认覆盖前四种。

---

## 12. 被拦截的判定标准（向导要能明确说「这家做不了」）

| 信号 | 判定 |
|---|---|
| 403 + 标题含 "Just a moment" / "Attention Required" / `cf-mitigated: challenge` | Cloudflare 挑战。headless 过不了；有窗口浏览器偶尔可过但不稳定（MoMA 经验）。**不做绕过。** |
| 307 到 `sucuri` 脚本 / `sucuri_cloudproxy` cookie | Sucuri JS 挑战，同上 |
| 403 静态 "Bad Bot Request" / SiteDistrict / Incapsula `_Incapsula_Resource` | WAF，同上 |
| 200 但 HTML 里没有任何时间 token，且浏览器渲染后才有 | 纯 JS 站点 → `render: browser`（非 Cloudflare 的 JS 站 headless 可行） |
| 200 但浏览器渲染后仍没有时间 token | 排片不在这个 URL 上，让用户换个链接（常见：给了首页而排片在 /calendar） |

纽约、旧金山湾区的影院即使被拦，也可以只配 `fallback: screenslate`（`SOURCES.md` §10）作为唯一数据源。

---

## 13. Webedia Movies Pro（Landmark Theatres 等连锁）— ★ 公开 JSON

2026‑10‑05 实测。Landmark Theatres（全美约 26 家）的网站是 Webedia 的 Gatsby 平台：网页源码里没有场次，浏览器用同站的公开 GET 接口加载，不需要签名或登录（另有一个带元数据的 `/api/cypher` 通用转发接口，不用它）。

```
GET <site>/api/gatsby-source-boxofficeapi/scheduledMovies?theaterId=X081D        # 哪些片在哪几天放（无时间）
GET <site>/api/gatsby-source-boxofficeapi/schedule?theaters={"id":"X081D","timeZone":"America/New_York"}
        &from=2026-10-05T03:00:00&to=2026-11-04T03:00:00&includeAllMovies=true
    -> {"X081D": {"schedule": {"<movieId>": {"2026-10-07": [{"startsAt": "2026-10-07T19:00:00", "tags": [...],
        "screen": {"name": "1"}, "data": {"ticketing": [{"provider": "default", "urls": [...]}]}}]}}}}
GET <site>/api/gatsby-source-boxofficeapi/movies?basic=false&castingLimit=3&ids=<id>&ids=<id>…
    -> title, release（首映日期）, runtime（**秒**）, directors.nodes[].person.{firstName,lastName}
```

- `theaters` 参数是「影院对象的 JSON 字符串」；一次请求可以覆盖一个月以上。影院编号是影院页路径的第一段：`/theaters/x081d-landmark-ritz-five-philadelphia/` → `X081D`。连锁的全站排片页（`/showtimes/`）不带影院，向导要的是单个影院页。
- 标签：`Format.Projection.35mm|70mm|16mm|Digital`；`Showtime.Accessibility.Subtitled`（字幕场）。`ClosedCaption`、`AudioDescription`、`Screen.Accessibility.HearingImpaired` 是个人辅助设备，不算银幕字幕。
- 片名可能带年份括号（"The Mummy (1932)"），和首映年份一致时去掉。影片页：`<site>/movies/<id>-<slug>/`。
- 适配器：`source: {adapter: boxofficeapi, site: "https://www.landmarktheatres.com", theater: X081D}`；向导在影院页上能自动识别。

## 14. Wix Events（Lightbox Film Center 等 Wix 站）— ★ 页面内嵌 JSON

2026‑10‑06 实测。Wix 建站的页面服务端就带着 Events 组件的数据：`<script type="application/json" id="wix-warmup-data">` 里
`appsWarmupData.<app id>.<widget id>.events.events[]`，一页可以有几个组件（「即将放映」「往期」各一个，`filterType` 不同）。单条：

```json
{"id": "b5eb…", "title": "Talking to Strangers", "slug": "talking-to-strangers", "description": "New Restoration",
 "location": {"name": "Bok Auditorium", "address": "800 Mifflin St, Philadelphia, PA 19148, USA", "coordinates": {"lat": 39.93, "lng": -75.16}},
 "scheduling": {"config": {"startDate": "2026-10-07T23:00:00.000Z", "endDate": "2026-10-08T01:00:00.000Z",
                           "timeZoneId": "America/New_York", "scheduleTbd": false, "recurrences": {"occurrences": []}}},
 "registration": {"type": 3, "external": {"registration": "https://events.ticketleap.com/tickets/…"},
                  "ticketing": {"soldOut": true}}}
```

- 时间是 UTC，`recurrences.occurrences[]` 非空时每项一个场次；`scheduleTbd` 的跳过。`endDate` 是活动时段（Lightbox 多为整 2 小时），作为 `end`。
- `description` 是一句话标语（"New Restoration"、"Philadelphia Premiere"、"Co-presented with …"），记为备注；`about` 常为空，导演 / 片长交给 TMDB。
- 票在别处卖（`registration.external`）时，Wix 自己的 `soldOut` 恒为 true，没有意义，只在用 Wix 售票时才标「Sold out」。购票链接 = `external.registration`；详情页取页面里指向 `/<slug>` 的链接（Lightbox 是 `/events/<slug>`），没有就用 Wix 默认的 `/event-details/<slug>`。
- 每场的 `location.name` 记为 `screen`：Lightbox 没有固定影厅，在 Bok Auditorium 之外也借用过别的场地，`venues.yaml` 的 `location.places` 按这个名字给出地址。
- Lightbox 首页组件只有最近 6 场，全量在 `/events-1`（`/events` 是单场详情页模板，只有 1 场）。探测：任一页面有 `wix-warmup-data` → 在首页链接里挑 `/events*`、`/calendar` 这类一段路径的页面，取「未开场的场次」最多的那页。
- 适配器：`source: {adapter: wix, pages: ['https://www.lightboxfilmcenter.org/events-1']}`，每页一次 GET，不另外请求；页面里抓取日一天以前的场次（往期组件）跳过。


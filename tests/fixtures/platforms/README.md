# 平台样本（2026‑09‑28 抓取）

真实页面 / 接口响应，供平台适配器、探测器、配方解释器离线开发与测试。结构说明见 `PLATFORMS.md`。

| 目录 | 文件 | 来源 | 用途 |
|---|---|---|---|
| `filmbot/` | `nitehawk_listings.json` | `https://nitehawkcinema.com/williamsburg/wp-json/nj/v1/showtime/listings` | 适配器正例（多分店路径） |
| | `brattle_listings.json`, `braindead_listings.json` | 同端点，`brattlefilm.org`、`studios.wearebraindead.com` | 适配器正例 |
| | `vidiots_showtime.json` | `vidiotsfoundation.org/wp-json/nj/v1/showtime` | 另一个端点形态（WP posts） |
| | `nitehawk_home.html` | `nitehawkcinema.com/williamsburg/` | 探测签名 |
| `veezi/` | `anthology_sessions.html` | `ticketing.us.veezi.com/sessions/?siteToken=bsrxtagjxmgh2qy0b6p646xdcr` | 售票页（HTML + JSON‑LD） |
| | `roxy_sessions.html`, `newbev_sessions.html`, `roxie_sessions.html` | `ticketing.uswest.veezi.com/...` | 同上，不同影院 |
| | `roxy_home.html` | `roxycinemanewyork.com` | 探测签名（`siteToken=`） |
| `agile/` | `gables_feed.json` | `prod3.agileticketing.net/websales/feed.ashx?guid=6ec0e98b-…` | 有内容的 feed（入口 GUID 可用） |
| | `gables_home.html` | `gablescinema.com` | 探测签名（`epguid=`） |
| | `coolidge_home.html`, `coolidge_feed_empty.json`, `siskel_feed_empty.json` | `coolidge.org`、`siskelfilmcenter.org` 及其可见 GUID 喂 feed 的结果 | 负例：GUID 不可用时应降级为 recipe |
| | PFS 的 feed 在 `tests/fixtures/filmadelphia/feed.json` | | |
| `tribe/` | `uniondocs_events.json`, `uniondocs_home.html` | `uniondocs.org/wp-json/tribe/events/v1/events` | 适配器正例 + 探测 |
| | `cinematheque_not_json.html` | `cinematheque.org/wp-json/tribe/...` 返回 HTML | 负例：必须检查 Content‑Type |
| `squarespace/` | `maysles_events.json` | `maysles.org/calendar?format=json` | 事件集合（`collection.typeName == events`） |
| | `maysles_calendar.json`, `maysles_home.html` | `maysles.org/maysles-calendar?format=json`、首页 | 负例（普通页 0 条）+ 探测签名 |
| `eventive/` | `cornell_home.html`, `cornell_tenant.js` | `cornellcinema.eventive.org` | 从 tenant bundle 抽 `event_bucket` / `api_key` |
| | `cornell_events.json` | `api.eventive.org/event_buckets/<id>/events` | 适配器正例 |
| | `nwff_calendar.html` | `nwfilmforum.org/calendar/` | 影院官网链到 eventive 的探测例 |
| `spektrix/` | `tyneside_events_filtered.json`, `tyneside_instances.json` | `system.spektrix.com/tynesidecinema/api/v3/...` | 适配器正例（英国站） |
| `jsonld/` | `bam_tony.html`, `vidiots_creepshow.html`, `brattle_elements.html` | 影片详情页 | `Event` / `ScreeningEvent` 正例 |
| | `filmforum_home_empty_dates.html` | `filmforum.org` | 负例：`startDate` 为空 |
| `ics/` | `uniondocs.ics` | `uniondocs.org/events/?ical=1` | 适配器正例 |
| `alamo/` | `nyc_schedule.json`, `nyc_home.html` | `drafthouse.com/s/mother/v2/schedule/market/nyc` | 适配器正例 |
| `wp_my_calendar/` | `trylon_events.json`, `trylon_home.html` | `trylon.org/wp-json/my-calendar/v1/events` | 适配器正例 |
| `recipe/` | `coolidge_home.html`, `siskel.html`, `belcourt.html`, `ifc.html`, `quad.html`, `hfa_calendar.html`, `bampfa_calendar.html`, `austinfilm_calendar.html`, `roxie_calendar.html`, `spectacle.html`, `lightindustry_calendar.html`, `paris_home.html`, `lightbox_calendar.html` | 各影院官网 | 服务端渲染但结构各异：配方解释器与配方生成的测试材料 |
| `blocked/` | `movingimage_cloudflare.html`, `hollywoodtheatre_cloudflare.html`, `musicbox_sucuri.html`, `cleveland_sucuri.html` | 挑战页原文 | 探测器「被拦截」判定的负例 |
| `js_only/` | `americancinematheque_now_showing.html`, `burns_film.html` | 官网 | 服务端无时间 token 的负例 |

抓取 UA 为桌面 Chrome；页面是抓取当日的快照，日期都在 2026‑09 / 10。

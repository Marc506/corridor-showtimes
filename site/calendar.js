/* Corridor Showtimes — "add to calendar" (iCalendar / .ics), no dependencies.
 * Pure functions (placeFor, eventFor, toICS, fileName) are also loaded by the offline tests under Node;
 * download() is the only part that touches the DOM.
 *
 * Apple Calendar shows a map for the event when it carries X-APPLE-STRUCTURED-LOCATION with coordinates
 * and that location's X-TITLE equals the LOCATION text; GEO and the plain LOCATION text ("Name, street
 * address") serve every other calendar. Coordinates and addresses come from venues.yaml `location:`.
 */
(function (root) {
  "use strict";

  const DEFAULT_MINUTES = 120;            // calendar block for a screening whose runtime is unknown
  const PRODID = "-//Corridor Showtimes//Showtimes//EN";
  const UID_DOMAIN = "corridor-showtimes";

  const LABELS = {
    zh: { tickets: "购票", details: "详情", minutes: (n) => `${n} 分钟`, runtimeUnknown: (n) => `片长未知，日历里先按 ${n / 60} 小时记` },
    en: { tickets: "Tickets", details: "Details", minutes: (n) => `${n} min`, runtimeUnknown: (n) => `Runtime unknown; blocked out as ${n / 60} hours` },
  };

  const lower = (x) => String(x || "").toLowerCase();

  /** The building a screening is in: a `places` entry whose `match` text appears in the screen name
   *  (case-insensitive), else the venue's own location. {name, address, geo} — address / geo may be null. */
  function placeFor(venue, screen) {
    const loc = (venue && venue.location) || {};
    const scr = lower(screen);
    const hit = scr && (loc.places || []).find((p) =>
      [].concat(p.match || []).some((m) => m && scr.includes(lower(m))));
    const src = hit || loc;
    return {
      name: src.name || (hit ? screen : null) || loc.name || (venue && venue.name) || "",
      address: src.address || null,
      geo: Array.isArray(src.geo) && src.geo.length === 2 ? src.geo : null,
    };
  }

  /** One screening -> a calendar event (times as Date objects, so the file is time-zone exact). */
  function eventFor(s, venue, lang = "en") {
    const L = LABELS[lang] || LABELS.en;
    const start = new Date(s.start);
    let end = s.end ? new Date(s.end) : null;
    if (!end && s.runtime_min) end = new Date(start.getTime() + s.runtime_min * 60e3);
    const endKnown = !!end;
    if (!end) end = new Date(start.getTime() + DEFAULT_MINUTES * 60e3);

    const place = placeFor(venue, s.screen);
    const location = place.address ? `${place.name}, ${place.address}` : place.name;
    const where = [venue && venue.name, s.screen && s.screen !== (venue && venue.name) ? s.screen : null].filter(Boolean).join(" · ");
    const meta = [s.director, s.year, s.runtime_min ? L.minutes(s.runtime_min) : null, s.format, s.language].filter(Boolean).join(" · ");
    const description = [
      where, meta, s.series, s.note,
      endKnown ? null : L.runtimeUnknown(DEFAULT_MINUTES),
      s.ticket_url ? `${L.tickets}: ${s.ticket_url}` : null,
      s.detail_url && s.detail_url !== s.ticket_url ? `${L.details}: ${s.detail_url}` : null,
    ].filter(Boolean).join("\n");

    return {
      uid: `${s.id}@${UID_DOMAIN}`,
      title: s.title,
      start, end, endKnown,
      location, place, description,
      url: s.ticket_url || s.detail_url || (venue && venue.website) || null,
    };
  }

  // ---------- iCalendar text (RFC 5545) ----------
  const utcStamp = (d) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");   // 20261006T230000Z
  const escText = (x) => String(x).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
  const quoteParam = (x) => `"${String(x).replace(/"/g, "'").replace(/[\r\n]+/g, " ")}"`;
  const utf8Len = (ch) => { const c = ch.codePointAt(0); return c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; };

  /** Fold a content line at 75 octets, never inside a UTF-8 character (continuation lines start with a space). */
  function fold(line) {
    const out = [];
    let cur = "", bytes = 0, limit = 75;
    for (const ch of line) {
      const n = utf8Len(ch);
      if (bytes + n > limit) { out.push(cur); cur = " "; bytes = 1; limit = 75; }
      cur += ch;
      bytes += n;
    }
    out.push(cur);
    return out.join("\r\n");
  }

  function vevent(ev, now) {
    const lines = [
      "BEGIN:VEVENT",
      `UID:${ev.uid}`,
      `DTSTAMP:${utcStamp(now)}`,
      `DTSTART:${utcStamp(ev.start)}`,
      `DTEND:${utcStamp(ev.end)}`,
      `SUMMARY:${escText(ev.title)}`,
    ];
    if (ev.location) lines.push(`LOCATION:${escText(ev.location)}`);
    const geo = ev.place && ev.place.geo;
    if (geo) {
      lines.push(`GEO:${geo[0]};${geo[1]}`);
      const params = ["VALUE=URI"];
      if (ev.place.address) params.push(`X-ADDRESS=${quoteParam(ev.place.address)}`);
      params.push("X-APPLE-RADIUS=70", `X-TITLE=${quoteParam(ev.location)}`);
      lines.push(`X-APPLE-STRUCTURED-LOCATION;${params.join(";")}:geo:${geo[0]},${geo[1]}`);
    }
    if (ev.description) lines.push(`DESCRIPTION:${escText(ev.description)}`);
    if (ev.url) lines.push(`URL:${ev.url}`);
    lines.push("END:VEVENT");
    return lines;
  }

  /** A complete VCALENDAR for one or more events, CRLF line endings. */
  function toICS(events, now = new Date()) {
    const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", `PRODID:${PRODID}`, "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
    for (const ev of [].concat(events)) lines.push(...vevent(ev, now));
    lines.push("END:VCALENDAR");
    return lines.map(fold).join("\r\n") + "\r\n";
  }

  /** "Happy Together 2026-10-06.ics" — the screening's own date, characters file systems refuse removed. */
  function fileName(s) {
    const title = String(s.title || "screening").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 60);
    return `${title} ${s.day || String(s.start).slice(0, 10)}.ics`;
  }

  // ---------- delivery ----------
  const UA = (root.navigator && root.navigator.userAgent) || "";
  const isIOS = () => /iPad|iPhone|iPod/.test(UA) ||
    (root.navigator && root.navigator.platform === "MacIntel" && root.navigator.maxTouchPoints > 1);
  /** iOS browsers other than Safari, and apps' built-in browsers (WeChat, Instagram …), don't hand
   *  .ics files to Calendar. */
  const iosNeedsSafari = () => isIOS() && /CriOS|FxiOS|EdgiOS|OPiOS|GSA\/|FBAN|FBAV|Instagram|Line\/|MicroMessenger|WeChat|QQ\//.test(UA);

  /** Hand the file to the system: iPhone / iPad Safari opens Calendar's "Add" sheet; desktop browsers
   *  download it, and opening the download adds it (Calendar on a Mac). A data: URL rather than a blob:
   *  URL, because iOS Safari previews calendar data: URLs directly. */
  function download(ics, filename) {
    const a = root.document.createElement("a");
    a.href = "data:text/calendar;charset=utf-8," + encodeURIComponent(ics);
    a.download = filename;
    a.rel = "noopener";
    a.style.display = "none";
    a.addEventListener("click", (e) => e.stopPropagation());   // not a click "outside" the page's popover
    root.document.body.append(a);
    a.click();
    a.remove();
  }

  const api = { DEFAULT_MINUTES, placeFor, eventFor, toICS, fileName, fold, download, isIOS, iosNeedsSafari };
  root.CinemaCalendar = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);

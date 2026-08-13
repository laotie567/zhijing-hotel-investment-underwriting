/**
 * Ctrip live-rate collector for market-evidence-collection/v2.
 *
 * This is intentionally a narrow adapter inside the underwriting Skill, not a
 * crawler service. Ui.Vision is the only component that changes the Ctrip
 * page. OpenCLI only binds the resulting tab and reads Network/DOM evidence.
 * The adapter never reads cookies, request headers, tokens or raw response
 * bodies into its result.
 */

import { createHash } from "node:crypto";
import { closeSync, openSync, readFileSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { pathToFileURL } from "node:url";

const CONTRACT_VERSION = "market-evidence-collection/v2";
const PROFILE = "ctrip-live-rates-v1";
const ENGINE = "ctrip-live-rates";
const MACRO_NAME = "zhijing-ctrip-wait-rates-v1";
const MAX_EMBEDDED_BYTES = 7_500_000;
const MAX_NETWORK_DETAILS = 24;
const MAX_IMAGES_PER_CANDIDATE = 4;
const LOCK_MAX_AGE_MS = 12 * 60 * 1_000;

function now() {
  return new Date().toISOString();
}

function compact(value, maximum = 2_000) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, maximum) : "";
}

function coverage(status, observed_count, notes) {
  return { status, observed_count, ...(notes ? { notes } : {}) };
}

function addNights(checkInDate, nights) {
  const value = new Date(`${checkInDate}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + Number(nights));
  return value.toISOString().slice(0, 10);
}

function redact(value, maximum = 500) {
  return compact(String(value || ""), maximum)
    .replace(/(cookie|authorization|token|session|password)\s*[:=]\s*[^\s,;]+/gi, "$1=[redacted]")
    .replace(/[A-Za-z0-9_-]{32,}/g, "[redacted]");
}

function issue(code, message, retryable, providerPlaceId) {
  return {
    code,
    message: compact(message, 500),
    retryable: Boolean(retryable),
    ...(providerPlaceId ? { provider_place_id: providerPlaceId } : {}),
  };
}

function ctripBookingUrl(ota, pricingContext) {
  let url;
  try {
    url = new URL(ota.property_url);
  } catch {
    return null;
  }
  if (!/(^|\.)ctrip\.com$/i.test(url.hostname)) return null;
  url.searchParams.set("hotelId", String(ota.property_id));
  url.searchParams.set("checkIn", pricingContext.check_in_date);
  url.searchParams.set("checkOut", addNights(pricingContext.check_in_date, pricingContext.nights));
  url.searchParams.set("adult", String(pricingContext.guests));
  url.searchParams.set("children", "0");
  url.searchParams.set("crn", "1");
  return url.toString();
}

function sanitizedPublicUrl(value) {
  try {
    const url = new URL(value);
    const allowed = new URLSearchParams();
    for (const key of ["hotelId", "hotelid", "checkIn", "checkOut", "adult", "children", "crn", "cityId"]) {
      if (url.searchParams.has(key)) allowed.set(key, url.searchParams.get(key));
    }
    url.search = allowed.toString();
    url.hash = "";
    return url.toString();
  } catch {
    return "";
  }
}

function normalizedName(value) {
  return compact(value, 300)
    .toLowerCase()
    .replace(/[（(].*?[)）]/g, "")
    .replace(/[\s\-_,，。·]/g, "")
    .replace(/(酒店|宾馆|民宿)$/g, "");
}

function mappingName(value) {
  return compact(value, 300)
    .split(/[，,]/, 1)[0]
    .toLowerCase()
    .replace(/[\s\-_,，。·()（）]/g, "");
}

function cityFromAddress(value) {
  const matched = compact(value, 500).match(/([\u4e00-\u9fff]{2,20})市/);
  return matched ? compact(matched[1], 40) : "";
}

function normalizedCity(value) {
  return compact(value, 80).replace(/市$/, "");
}

function parseJson(value) {
  if (typeof value !== "string") return null;
  try {
    return JSON.parse(value);
  } catch {
    const start = value.indexOf("{");
    const end = value.lastIndexOf("}");
    if (start >= 0 && end > start) {
      try { return JSON.parse(value.slice(start, end + 1)); } catch { return null; }
    }
    const arrayStart = value.indexOf("[");
    const arrayEnd = value.lastIndexOf("]");
    if (arrayStart >= 0 && arrayEnd > arrayStart) {
      try { return JSON.parse(value.slice(arrayStart, arrayEnd + 1)); } catch { return null; }
    }
    return null;
  }
}

function readMcpText(result) {
  const content = result && Array.isArray(result.content) ? result.content : [];
  return content
    .filter((item) => item && item.type === "text" && typeof item.text === "string")
    .map((item) => item.text)
    .join("\n");
}

class McpStdioClient {
  constructor(command) {
    this.command = command;
    this.sequence = 0;
    this.pending = new Map();
    this.stderr = "";
    this.buffer = "";
  }

  async start() {
    const [executable, ...args] = this.command;
    this.process = spawn(executable, args, { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    this.process.stdout.setEncoding("utf8");
    this.process.stderr.setEncoding("utf8");
    this.process.stdout.on("data", (chunk) => this._onStdout(chunk));
    this.process.stderr.on("data", (chunk) => { this.stderr = (this.stderr + chunk).slice(-4_000); });
    this.process.on("error", (error) => this._failAll(error));
    this.process.on("exit", (code) => {
      if (code !== 0) this._failAll(new Error(`Ui.Vision bridge exited (${code})`));
    });
    await this.call("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "zhijing-ctrip-collector", version: "1" } }, 15_000);
  }

  _onStdout(chunk) {
    this.buffer += chunk;
    let next;
    while ((next = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, next).trim();
      this.buffer = this.buffer.slice(next + 1);
      if (!line) continue;
      let message;
      try { message = JSON.parse(line); } catch { continue; }
      const pending = this.pending.get(message.id);
      if (!pending) continue;
      clearTimeout(pending.timer);
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(compact(message.error.message || "MCP error", 500)));
      else pending.resolve(message.result);
    }
  }

  _failAll(error) {
    for (const [id, pending] of this.pending.entries()) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }

  call(method, params, timeoutMs) {
    const id = ++this.sequence;
    const timeout = timeoutMs || 180_000;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Ui.Vision bridge timed out calling ${method}`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.process.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  async tool(name, args = {}, timeoutMs) {
    return this.call("tools/call", { name, arguments: args }, timeoutMs);
  }

  stop() {
    if (this.process && !this.process.killed) this.process.kill("SIGTERM");
  }
}

function bridgeCommand() {
  const configured = compact(process.env.MARKET_EVIDENCE_UIVISION_BRIDGE_COMMAND || "", 500);
  if (configured) return configured.split(/\s+/);
  return ["uivision-mcp-bridge"];
}

function fixedMacro() {
  return {
    Name: MACRO_NAME,
    Commands: [
      { Command: "store", Target: "MEDIUM", Value: "!replayspeed" },
      { Command: "store", Target: "30", Value: "!timeout_wait" },
      { Command: "refresh", Target: "", Value: "" },
      { Command: "waitForElementPresent", Target: "css=body", Value: "" },
      { Command: "pause", Target: "5000", Value: "" },
    ],
  };
}

async function ensureMacro(bridge) {
  const listingText = readMcpText(await bridge.tool("list_macros"));
  let macroName = "";
  const listing = parseJson(listingText);
  if (Array.isArray(listing)) {
    const matched = listing.find((item) => item && typeof item.name === "string" && item.name.includes(MACRO_NAME));
    if (matched) macroName = matched.name;
  }
  if (!macroName && listingText.includes(MACRO_NAME)) macroName = MACRO_NAME;
  if (!macroName) {
    await bridge.tool("create_macro", { macro_json: JSON.stringify(fixedMacro()), why: "Install the versioned, fixed Ctrip rate-refresh macro." });
    const secondListing = readMcpText(await bridge.tool("list_macros"));
    const parsed = parseJson(secondListing);
    if (Array.isArray(parsed)) {
      const matched = parsed.find((item) => item && typeof item.name === "string" && item.name.includes(MACRO_NAME));
      if (matched) macroName = matched.name;
    }
    if (!macroName && secondListing.includes(MACRO_NAME)) macroName = MACRO_NAME;
  }
  if (!macroName) throw new Error("Ui.Vision did not expose the fixed Ctrip refresh macro");
  await bridge.tool("open_macro", { name: macroName, why: "Run the fixed Ctrip rate-refresh macro." });
  return macroName;
}

function runProcess(command, timeoutMs = 60_000) {
  const [executable, ...args] = command;
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`${executable} timed out`));
    }, timeoutMs);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => { clearTimeout(timer); reject(error); });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(redact(stderr || stdout || `${executable} exited ${code}`)));
    });
  });
}

async function openCli(args, timeoutMs) {
  const response = await runProcess(["opencli", ...args], timeoutMs);
  const json = parseJson(response.stdout);
  return { ...response, json };
}

function lockIsStale(lockPath, referenceTime = Date.now()) {
  try {
    const metadata = JSON.parse(readFileSync(lockPath, "utf8"));
    const pid = Number(metadata?.pid);
    if (Number.isInteger(pid) && pid > 0) {
      try {
        // A live job may legitimately exceed the normal age threshold while
        // eight rate pages wait for a human browser. Never steal that lock.
        process.kill(pid, 0);
        return false;
      } catch (error) {
        return error?.code === "ESRCH";
      }
    }
    const startedAt = Date.parse(metadata?.started_at || "");
    return Number.isFinite(startedAt) && referenceTime - startedAt > LOCK_MAX_AGE_MS;
  } catch {
    try {
      return referenceTime - statSync(lockPath).mtimeMs > LOCK_MAX_AGE_MS;
    } catch {
      return false;
    }
  }
}

function acquireLock(retried = false) {
  const lockPath = path.join(os.tmpdir(), "zhijing-ctrip-price-worker.lock");
  try {
    const fd = openSync(lockPath, "wx");
    writeFileSync(fd, JSON.stringify({ pid: process.pid, started_at: now() }));
    return () => {
      try { closeSync(fd); } catch { /* nothing to do */ }
      try { unlinkSync(lockPath); } catch { /* nothing to do */ }
    };
  } catch {
    if (!retried && lockIsStale(lockPath)) {
      try { unlinkSync(lockPath); } catch { /* another process resolved it */ }
      return acquireLock(true);
    }
    throw new Error("Ctrip price worker is busy; wait for the active collection to finish");
  }
}

function extractPropertyId(value) {
  const fromUrl = compact(value, 1_000).match(/[?&]hotelid=(\d+)|\/detail\/(\d+)/i);
  return fromUrl ? (fromUrl[1] || fromUrl[2]) : "";
}

async function resolveOtaProperty(item, city) {
  if (item.ota_property) return { ota: item.ota_property, issue: null };
  const candidate = item.candidate || {};
  if (!city) {
    return { ota: null, issue: issue("HOTEL_MAPPING_AMBIGUOUS", "目标地址未提供可核验城市；不会自动按酒店名称映射携程报价页。", true, candidate.provider_place_id) };
  }
  let response;
  try {
    response = await openCli(["ctrip", "search", candidate.name, "--limit", "10", "--format", "json"], 30_000);
  } catch {
    return { ota: null, issue: issue("HOTEL_MAPPING_AMBIGUOUS", "携程酒店映射查询未返回可核验结果。", true, candidate.provider_place_id) };
  }
  const matches = (Array.isArray(response.json) ? response.json : [])
    .filter((record) => record && typeof record === "object")
    .filter((record) => mappingName(record.name) === mappingName(candidate.name))
    .filter((record) => normalizedCity(record.cityName) === normalizedCity(city));
  if (matches.length !== 1 || !matches[0].url || !(matches[0].id || extractPropertyId(matches[0].url))) {
    return { ota: null, issue: issue("HOTEL_MAPPING_AMBIGUOUS", "携程搜索未形成唯一的酒店实体映射；不会按名称猜测报价页。", true, candidate.provider_place_id) };
  }
  const match = matches[0];
  return {
    ota: {
      platform: "携程",
      property_id: String(match.id || extractPropertyId(match.url)),
      property_url: sanitizedPublicUrl(match.url),
      match_method: "ctrip_search_exact_name",
      matched_at: now(),
    },
    issue: null,
  };
}

function numberAt(value, keys) {
  for (const key of keys) {
    const entry = value && value[key];
    const normalized = typeof entry === "string" ? Number(entry.replace(/[￥¥,\s]/g, "")) : Number(entry);
    if (Number.isFinite(normalized) && normalized > 0 && normalized < 100_000) return normalized;
  }
  return null;
}

function textAt(value, keys) {
  for (const key of keys) {
    const entry = value && value[key];
    if (typeof entry === "string" && compact(entry)) return compact(entry, 300);
  }
  return "";
}

function detectAvailability(value) {
  const raw = textAt(value, ["availability", "inventoryStatus", "saleStatus", "bookStatus", "status"]);
  if (value?.available === true || value?.canBook === true || /available|可订|有房|正常/i.test(raw)) return "available";
  if (value?.available === false || value?.canBook === false || /sold|满房|无房|不可订|售罄|已订完/i.test(raw)) return "sold_out";
  return "unknown";
}

function taxIncludedFromText(value) {
  const raw = compact(value, 1_500);
  if (/不含税|另付税|税费另计/.test(raw)) return false;
  if (/含税|税费已含/.test(raw)) return true;
  return null;
}

function workstationCount(value) {
  const matches = compact(value, 500).match(/(\d+)\s*(?:台|机)(?:电竞)?(?:电脑|位)?/i);
  if (!matches) return null;
  const count = Number(matches[1]);
  return Number.isInteger(count) && count >= 1 && count <= 12 ? count : null;
}

function networkRates(body, endpoint) {
  const result = [];
  const seen = new Set();
  const visit = (node, depth = 0) => {
    if (depth > 12 || node === null || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const item of node.slice(0, 300)) visit(item, depth + 1);
      return;
    }
    const roomName = textAt(node, ["roomName", "roomTypeName", "baseRoomName", "roomDisplayName", "name"]);
    const price = numberAt(node, ["payPrice", "salePrice", "displayPrice", "price", "amount", "totalPrice"]);
    if (roomName && roomName.includes("房") && price !== null) {
      const ratePlan = textAt(node, ["ratePlanName", "rateName", "productName", "priceName"]);
      const identifier = textAt(node, ["roomId", "roomTypeId", "baseRoomId", "id"]);
      const key = `${identifier}|${roomName}|${ratePlan}|${price}`;
      if (!seen.has(key)) {
        seen.add(key);
        const cancellation = textAt(node, ["cancelPolicy", "cancelText", "cancelDescription", "refundPolicy"]);
        result.push({
          room_id: identifier || null,
          room_name: roomName,
          rate_plan_name: ratePlan || null,
          price,
          availability: detectAvailability(node),
          cancellation_policy: cancellation || null,
          tax_included: taxIncludedFromText(JSON.stringify(node)),
          endpoint_path: endpoint,
        });
      }
    }
    for (const item of Object.values(node)) visit(item, depth + 1);
  };
  visit(body);
  return result.slice(0, 80);
}

function domRates(facts) {
  const rows = [];
  const seen = new Set();
  for (const block of Array.isArray(facts?.room_blocks) ? facts.room_blocks : []) {
    const text = compact(block?.text, 1_500);
    if (!text || !text.includes("房")) continue;
    const roomName = text.split("\n").map((line) => compact(line, 300)).find((line) => line.includes("房")) || "";
    const values = [...text.matchAll(/(?:￥|¥)\s*([0-9][0-9,]*)/g)]
      .map((match) => Number(match[1].replace(/,/g, "")))
      .filter((value) => Number.isFinite(value) && value > 0);
    if (!roomName || values.length !== 1) continue;
    const cancellation = (text.match(/(?:免费取消|不可取消|取消[^，。\n]{0,80})/) || [""])[0] || null;
    const id = compact(block?.room_id || "", 200) || null;
    const key = `${id}|${roomName}|${values[0]}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({
      room_id: id,
      room_name: roomName,
      price: values[0],
      availability: /已订完|售罄|满房|不可订/.test(text) ? "sold_out" : (/可订|立即预订/.test(text) ? "available" : "unknown"),
      cancellation_policy: cancellation,
      tax_included: taxIncludedFromText(text),
      workstations: workstationCount(text),
    });
  }
  return rows.slice(0, 80);
}

function verifyContext(body, pricingContext) {
  const checkout = addNights(pricingContext.check_in_date, pricingContext.nights);
  const [, inMonth, inDay] = pricingContext.check_in_date.split("-").map(Number);
  const [, outMonth, outDay] = checkout.split("-").map(Number);
  const source = compact(body, 120_000);
  const dates = (source.includes(pricingContext.check_in_date) && source.includes(checkout)) ||
    (source.includes(`${inMonth}月${inDay}日`) && source.includes(`${outMonth}月${outDay}日`));
  const people = source.includes(`${pricingContext.guests}成人`) || source.includes(`${pricingContext.guests}位成人`);
  return dates && people;
}

function matchRates(network, dom) {
  const matches = [];
  for (const rate of network) {
    const byId = rate.room_id ? dom.find((item) => item.room_id && item.room_id === rate.room_id && item.price === rate.price) : null;
    const byName = dom.find((item) => normalizedName(item.room_name) === normalizedName(rate.room_name) && item.price === rate.price);
    const matched = byId || byName;
    matches.push({ network: rate, dom: matched || null, price_match: Boolean(matched) });
  }
  return matches;
}

function observation(match, context, sourceUrl, observedAt, contextVerified = true) {
  const rate = match.network;
  const dom = match.dom;
  const gaps = [];
  if (!contextVerified) gaps.push("pricing_context_unverified");
  if (!match.price_match) gaps.push("network_dom_price_mismatch");
  if (rate.availability !== "available") gaps.push("availability_not_confirmed");
  if (rate.tax_included === null || dom?.tax_included === null) gaps.push("tax_scope_unknown");
  if (!rate.cancellation_policy && !dom?.cancellation_policy) gaps.push("cancellation_policy_missing");
  const workstation = dom?.workstations || workstationCount(rate.room_name);
  if (!workstation) gaps.push("workstations_missing");
  return {
    room_type: rate.room_name,
    room_type_provider_id: rate.room_id,
    rate_plan_name: rate.rate_plan_name,
    price_type: "P2",
    display_price: rate.price,
    currency: "CNY",
    availability: rate.availability,
    pricing_context: context,
    source_url: sourceUrl,
    observed_at: observedAt,
    network_verified: true,
    dom_verified: Boolean(dom),
    price_match: match.price_match,
    adr_eligible: gaps.length === 0,
    qualification_gaps: gaps,
    ...(workstation ? { workstations: workstation } : {}),
  };
}

async function fetchImage(imageUrl, pageSources, remainingBytes) {
  try {
    const response = await fetch(imageUrl, { redirect: "follow" });
    const sanitized = sanitizedPublicUrl(imageUrl);
    if (sanitized) pageSources.push({ url: sanitized, status: response.status });
    if (!response.ok) return null;
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > remainingBytes) return null;
    let mime = compact(response.headers.get("content-type") || "", 100).split(";", 1)[0].toLowerCase();
    if (!/^image\/(jpeg|png|webp)$/.test(mime)) return null;
    return {
      data_uri: `data:${mime};base64,${buffer.toString("base64")}`,
      mime_type: mime,
      sha256: createHash("sha256").update(buffer).digest("hex"),
    };
  } catch {
    return null;
  }
}

const DOM_FACTS_SCRIPT = `(() => {
  const compact = (v, n = 1500) => String(v || '').replace(/\\s+/g, ' ').trim().slice(0, n);
  const body = String(document.body?.innerText || '').slice(0, 120000);
  const imageContext = (image) => [
    image.alt, image.className, image.parentElement?.className,
    image.parentElement?.parentElement?.className
  ].map((value) => String(value || '')).join(' ');
  const images = [...document.images].map((image) => ({
    url: compact(image.currentSrc || image.src || image.getAttribute('data-src'), 4000),
    alt: compact(image.alt, 240), width: Number(image.naturalWidth || image.width || 0),
    height: Number(image.naturalHeight || image.height || 0), context: imageContext(image)
  })).filter((item) => item.url.startsWith('http') && item.width >= 160 && item.height >= 100)
    .filter((item) => /酒店|房型|客房|room|hotel|gallery|album/i.test(item.context))
    .filter((item) => !/avatar|logo|qrcode|二维码/i.test(item.context)).slice(0, 12);
  const blocks = []; const seen = new Set();
  for (const element of [...document.querySelectorAll('div,li,section,article')]) {
    const text = String(element.innerText || '').trim();
    if (!text.includes('房') || !/(￥|¥)\\s*\\d/.test(text) || text.length > 1800 || seen.has(text)) continue;
    seen.add(text);
    blocks.push({ text, room_id: element.getAttribute('data-room-id') || element.getAttribute('data-roomid') || element.getAttribute('data-room-type-id') || '' });
    if (blocks.length >= 80) break;
  }
  return { title: document.title, body, images, room_blocks: blocks };
})()`;

async function collectOne(bridge, item, request, pageSources, imageBudget) {
  const candidate = item.candidate;
  const mapping = await resolveOtaProperty(item, cityFromAddress(request.target.address));
  if (!mapping.ota) return { candidate, issue: mapping.issue, roomTypes: [], observations: [], offers: [], media: null, noInventory: false };
  const bookingUrl = ctripBookingUrl(mapping.ota, request.pricing_context);
  if (!bookingUrl) {
    return { candidate, issue: issue("HOTEL_MAPPING_AMBIGUOUS", "携程映射 URL 不属于允许的携程域名。", false, candidate.provider_place_id), roomTypes: [], observations: [], offers: [], media: null, noInventory: false };
  }
  const safeUrl = sanitizedPublicUrl(bookingUrl);
  try {
    await bridge.tool("get_page", { url: bookingUrl, why: "Open the explicitly mapped Ctrip property with the requested stay context." }, 120_000);
    if (safeUrl) pageSources.push({ url: safeUrl, status: 200 });
    const session = `zhijing-ctrip-${String(candidate.provider_place_id).replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 48)}`;
    await openCli(["browser", session, "bind"], 30_000);
    const before = await openCli(["browser", session, "network", "--since", "2m"], 30_000);
    const beforeKeys = new Set(Array.isArray(before.json?.entries) ? before.json.entries.map((entry) => entry.key) : []);
    await bridge.tool("run_macro", { why: "Refresh the Ctrip rate page through the fixed versioned macro." }, 180_000);
    const after = await openCli(["browser", session, "network", "--since", "2m"], 30_000);
    const entries = Array.isArray(after.json?.entries) ? after.json.entries : [];
    const candidateEntries = entries
      .filter((entry) => !beforeKeys.has(entry.key))
      .filter((entry) => /room|hotel|rate|price|book/i.test(String(entry.url || "") + JSON.stringify(entry.shape || "")))
      .slice(-MAX_NETWORK_DETAILS);
    const network = [];
    for (const entry of candidateEntries) {
      let detail;
      try { detail = await openCli(["browser", session, "network", "--detail", String(entry.key), "--max-body", "300000"], 30_000); } catch { continue; }
      const rawBody = detail.json?.body;
      const body = typeof rawBody === "string" ? parseJson(rawBody) : rawBody;
      if (body && typeof body === "object") network.push(...networkRates(body, new URL(entry.url).pathname));
    }
    const factResponse = await openCli(["browser", session, "eval", DOM_FACTS_SCRIPT], 30_000);
    const facts = factResponse.json && typeof factResponse.json === "object" ? factResponse.json : {};
    const observedAt = now();
    const dom = domRates(facts);
    const contextVerified = verifyContext(facts.body, request.pricing_context);
    const matches = matchRates(network, dom);
    const observations = matches.map((match) => observation(
      match,
      request.pricing_context,
      safeUrl,
      observedAt,
      contextVerified,
    ));
    const roomTypes = [...new Set([
      ...dom.map((row) => row.room_name),
      ...network.map((row) => row.room_name),
    ].filter(Boolean))];
    const offers = observations
      .filter((row) => row.adr_eligible)
      .map((row) => ({
        room_type: row.room_type,
        room_type_provider_id: row.room_type_provider_id || `${mapping.ota.property_id}:network:${row.room_type}`,
        workstations: row.workstations,
        nightly_price: row.display_price,
        availability: row.availability,
        currency: "CNY",
        tax_included: true,
        cancellation_policy: "页面与网络均已验证",
        pricing_context: request.pricing_context,
        source_url: safeUrl,
        observed_at: observedAt,
      }));
    const images = [];
    for (const image of (Array.isArray(facts.images) ? facts.images : []).slice(0, Math.min(request.search.max_images_per_candidate, MAX_IMAGES_PER_CANDIDATE))) {
      const itemImage = await fetchImage(image.url, pageSources, imageBudget.remainingBytes);
      if (!itemImage) continue;
      const encodedBytes = Buffer.byteLength(itemImage.data_uri, "utf8");
      if (encodedBytes > imageBudget.remainingBytes) continue;
      imageBudget.remainingBytes -= encodedBytes;
      images.push({
        caption: compact(image.alt || "携程公开酒店/房型图（仅作视觉对标）", 240),
        data_uri: itemImage.data_uri,
        source_url: sanitizedPublicUrl(image.url),
        observed_at: observedAt,
        mime_type: itemImage.mime_type,
        sha256: itemImage.sha256,
      });
    }
    const noInventory = /不接受预订|暂无房|已订完|售罄|满房|不可订/.test(compact(facts.body, 120_000)) && !observations.length;
    let collectionIssue = null;
    if (/登录看低价|请登录/.test(compact(facts.body, 120_000))) collectionIssue = issue("AUTH_REQUIRED", "携程页面要求登录后才能展示同条件价格。", true, candidate.provider_place_id);
    else if (/验证码|安全验证|滑动验证/.test(compact(facts.body, 120_000))) collectionIssue = issue("CAPTCHA_REQUIRED", "携程页面要求人工完成安全验证。", true, candidate.provider_place_id);
    else if (!contextVerified) collectionIssue = issue("QUERY_MISMATCH", "页面未展示与请求一致的入住日期和人数；不会使用页面价格。", true, candidate.provider_place_id);
    else if (noInventory) collectionIssue = issue("NO_INVENTORY", "已在请求条件下确认该竞品暂无可订房型。", false, candidate.provider_place_id);
    else if (!network.length && !dom.length) collectionIssue = issue("RATE_LOAD_TIMEOUT", "携程页面未返回可识别的房型/报价数据。", true, candidate.provider_place_id);
    else if (network.length && !matches.some((match) => match.price_match)) collectionIssue = issue("PRICE_MISMATCH", "Network 与页面房型报价未形成可验证匹配。", true, candidate.provider_place_id);
    return {
      candidate: {
        ...candidate,
        benchmark_selected: true,
        booking_evidence: [{ ...mapping.ota, property_url: safeUrl, observed_at: observedAt, page_title: compact(facts.title, 300) }],
        room_offers: contextVerified ? offers : [],
        pricing_observations: observations,
      },
      issue: collectionIssue,
      roomTypes,
      observations,
      offers,
      media: images.length ? {
        provider_place_id: candidate.provider_place_id,
        renovation_observation: "来源为携程公开房型/酒店图片；仅供装修、机位环境和空间状态的人工对标，不替代实勘。",
        observation_source_url: safeUrl,
        images,
      } : null,
      noInventory,
      contextVerified,
    };
  } catch (error) {
    return {
      candidate,
      issue: issue("RPA_FAILED", `携程页面动作或观察失败：${redact(error.message || error, 240)}`, true, candidate.provider_place_id),
      roomTypes: [], observations: [], offers: [], media: null, noInventory: false,
    };
  }
}

function baseResult(request, startedAt) {
  return {
    contract_version: CONTRACT_VERSION,
    ...(request.request_id ? { request_id: request.request_id } : {}),
    status: "failed",
    collector: {
      engine: ENGINE,
      engine_version: "uivision-opencli/ctrip-live-rates-v1",
      source_profile: PROFILE,
      started_at: startedAt,
      finished_at: startedAt,
      page_sources: [],
    },
    target_resolution: request.target.center || null,
    coverage: {
      candidates: coverage("failed", 0), benchmark_set: coverage("failed", 0),
      room_types: coverage("failed", 0), images: coverage("failed", 0), pricing: coverage("failed", 0),
    },
    collection_gaps: [],
    collection_issues: [],
    competitor_analysis: {
      confirmed_location: request.target.center || null,
      collection_status: "partial",
      pricing_context: request.pricing_context,
      candidates: [],
    },
    competitor_report: { title: `${request.target.name}：2km电竞竞品携程报价与视觉证据`, candidate_media: [] },
    // An OTA adapter must echo the immutable map-pool proof even when its
    // browser bridge fails before it can collect a single property page.
    spatial_collection: request.candidate_pool,
  };
}

async function collect(request) {
  if (request.contract_version !== CONTRACT_VERSION) throw new Error("unsupported market evidence contract");
  if (request.search?.provider_profile !== PROFILE) throw new Error(`${ENGINE} requires ${PROFILE}`);
  const result = baseResult(request, now());
  const inventory = Array.isArray(request.candidate_inventory) ? request.candidate_inventory : [];
  const selected = inventory.filter((item) => item?.benchmark_selected === true);
  const candidates = inventory.map((item) => ({
    ...item.candidate,
    benchmark_selected: item.benchmark_selected === true,
    booking_evidence: item.ota_property ? [{ ...item.ota_property }] : [],
    room_offers: [],
    pricing_observations: [],
  }));
  // The map profile owns the 2km boundary.  Preserve its completed population
  // on every return path; live pricing and visual coverage are separate axes.
  result.competitor_analysis.collection_status = request.candidate_pool.status;
  result.competitor_analysis.candidates = candidates;
  result.coverage.candidates = coverage("complete", candidates.length);
  result.coverage.benchmark_set = coverage("complete", selected.length);
  if (!inventory.length || !selected.length) {
    result.collection_gaps.push("ctrip-live-rates 需要完整 2km candidate_inventory 和至少一个标记的 benchmark_selected 候选。");
    result.collector.finished_at = now();
    return result;
  }
  let release;
  let bridge;
  try {
    release = acquireLock();
    bridge = new McpStdioClient(bridgeCommand());
    await bridge.start();
    const bridgeStatus = readMcpText(await bridge.tool("bridge_status"));
    if (/NOT connected|not connected/i.test(bridgeStatus)) {
      result.collection_issues.push(issue("UIVISION_UNPAIRED", "Ui.Vision 扩展尚未与本机 MCP Bridge 配对；没有执行携程页面动作。", true));
      result.collection_gaps.push("Ui.Vision 未配对；请在 ctrip-price-worker Chrome Profile 中完成配对后重试。");
      return result;
    }
    await ensureMacro(bridge);
    const pageSources = result.collector.page_sources;
    const outcomes = [];
    const imageBudget = { remainingBytes: MAX_EMBEDDED_BYTES };
    for (const item of selected) outcomes.push(await collectOne(bridge, item, request, pageSources, imageBudget));
    const byId = new Map(outcomes.map((outcome) => [outcome.candidate.provider_place_id, outcome.candidate]));
    result.competitor_analysis.candidates = candidates.map((candidate) => byId.get(candidate.provider_place_id) || candidate);
    result.competitor_report.candidate_media = outcomes.map((outcome) => outcome.media).filter(Boolean);
    result.collection_issues = outcomes.map((outcome) => outcome.issue).filter(Boolean);
    const roomTypes = outcomes.reduce((sum, outcome) => sum + outcome.roomTypes.length, 0);
    const priceObserved = outcomes.filter((outcome) => outcome.contextVerified && (outcome.observations.length || outcome.noInventory)).length;
    const imageObserved = outcomes.filter((outcome) => outcome.media?.images?.length).length;
    const retryableIssues = result.collection_issues.filter((item) => item.retryable);
    const roomTypesComplete = !request.required_evidence.room_types || roomTypes > 0;
    const imagesComplete = !request.required_evidence.images || imageObserved === selected.length;
    const pricingComplete = !request.required_evidence.pricing || priceObserved === selected.length;
    const complete = retryableIssues.length === 0 && roomTypesComplete && imagesComplete && pricingComplete;
    result.coverage = {
      candidates: coverage("complete", candidates.length),
      benchmark_set: coverage("complete", selected.length),
      room_types: coverage(roomTypesComplete ? "complete" : "partial", roomTypes),
      images: coverage(imagesComplete ? "complete" : "partial", imageObserved),
      pricing: coverage(pricingComplete ? "complete" : "partial", priceObserved),
    };
    result.collection_gaps = result.collection_issues.map((item) => `${item.code}：${item.message}`);
    // Price coverage may remain partial, but this collector was handed the
    // exact completed map pool. Preserve the spatial conclusion and let ADR
    // eligibility depend on the price coverage/offer gates instead.
    result.competitor_analysis.collection_status = request.candidate_pool.status;
    result.spatial_collection = request.candidate_pool;
    result.status = complete ? "complete" : "partial";
    return result;
  } catch (error) {
    const code = /busy/i.test(String(error?.message)) ? "BROWSER_DISCONNECTED" : "RPA_FAILED";
    result.collection_issues.push(issue(code, redact(error?.message || error, 400), true));
    result.collection_gaps.push(`${code}：无法启动携程实时价格采集。`);
    return result;
  } finally {
    result.collector.finished_at = now();
    if (bridge) bridge.stop();
    if (release) release();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const raw = process.env.MARKET_EVIDENCE_REQUEST_JSON;
  if (!raw) throw new Error("MARKET_EVIDENCE_REQUEST_JSON is required");
  const request = JSON.parse(raw);
  const result = await collect(request);
  console.log(JSON.stringify(result));
}

export {
  addNights,
  cityFromAddress,
  ctripBookingUrl,
  domRates,
  lockIsStale,
  mappingName,
  matchRates,
  networkRates,
  normalizedName,
  observation,
  verifyContext,
};

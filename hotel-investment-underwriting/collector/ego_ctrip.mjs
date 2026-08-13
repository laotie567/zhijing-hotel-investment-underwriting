/**
 * Ego Lite implementation of the Ctrip booking/visual evidence profile.
 *
 * It is evaluated by `ego-browser nodejs`, not by Node directly. The Python
 * host injects MARKET_EVIDENCE_REQUEST_JSON and closes the task space in a
 * dedicated follow-up command after this script returns one JSON envelope.
 *
 * The profile never estimates a rate. A room offer is emitted only when the
 * rendered booking page ties one room card to an available, dated price and
 * exposes its cancellation/tax scope. Otherwise the observation stays partial.
 */

const CONTRACT_VERSION = "market-evidence-collection/v1";
const PROFILE = "ctrip-hotel-v1";
const MAX_EMBEDDED_BYTES = 7_500_000;
const { createHash } = await import("node:crypto");

function now() {
  return new Date().toISOString();
}

function text(value, maximum = 2_000) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, maximum) : "";
}

function coverage(status, observed_count, notes) {
  return { status, observed_count, ...(notes ? { notes } : {}) };
}

function addNights(checkInDate, nights) {
  const start = new Date(`${checkInDate}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() + Number(nights));
  return start.toISOString().slice(0, 10);
}

function ctripBookingUrl(property, pricingContext) {
  const parameters = new URLSearchParams({
    hotelId: property.property_id,
    checkIn: pricingContext.check_in_date,
    checkOut: addNights(pricingContext.check_in_date, pricingContext.nights),
    adult: String(pricingContext.guests),
    children: "0",
    crn: "1",
  });
  if (property.city_id) parameters.set("cityId", property.city_id);
  return `https://hotels.ctrip.com/hotels/detail/?${parameters.toString()}`;
}

function dataUri(buffer, contentType) {
  const bytes = new Uint8Array(buffer);
  let mime = typeof contentType === "string" ? contentType.split(";", 1)[0].toLowerCase() : "";
  if (!/^image\/(jpeg|png|webp)$/.test(mime)) {
    if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) mime = "image/jpeg";
    else if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) mime = "image/png";
    else if (bytes.length >= 12 && String.fromCharCode(...bytes.slice(0, 4)) === "RIFF" && String.fromCharCode(...bytes.slice(8, 12)) === "WEBP") mime = "image/webp";
  }
  if (!/^image\/(jpeg|png|webp)$/.test(mime)) return null;
  return { data_uri: `data:${mime};base64,${Buffer.from(buffer).toString("base64")}`, mime_type: mime };
}

async function fetchImage(imageUrl, pageSources, remainingBytes) {
  try {
    const response = await fetch(imageUrl, { redirect: "follow" });
    const status = response.status;
    pageSources.push({ url: imageUrl, status });
    if (!response.ok) return null;
    const body = await response.arrayBuffer();
    if (body.byteLength > remainingBytes) return null;
    const image = dataUri(body, response.headers.get("content-type"));
    return image ? {
      ...image,
      sha256: createHash("sha256").update(Buffer.from(body)).digest("hex"),
      bytes: body.byteLength,
    } : null;
  } catch {
    pageSources.push({ url: imageUrl, status: 599 });
    return null;
  }
}

function buildBaseResult(request, startedAt, pageSources) {
  return {
    contract_version: CONTRACT_VERSION,
    ...(request.request_id ? { request_id: request.request_id } : {}),
    status: "failed",
    collector: {
      engine: "ego-browser",
      engine_version: "ego-lite/ctrip-dom-v1",
      source_profile: PROFILE,
      started_at: startedAt,
      finished_at: now(),
      page_sources: pageSources,
    },
    target_resolution: request.target.center || null,
    coverage: {
      candidates: coverage("failed", 0),
      benchmark_set: coverage("failed", 0),
      room_types: coverage("failed", 0),
      images: coverage("failed", 0),
      pricing: coverage("failed", 0),
    },
    collection_gaps: [],
    competitor_analysis: {
      confirmed_location: request.target.center || null,
      collection_status: "partial",
      pricing_context: request.pricing_context,
      candidates: [],
    },
    competitor_report: { candidate_media: [] },
  };
}

function extractPageFacts(maxImages) {
  return js(String.raw`(() => {
    const compact = (value, maximum = 2000) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, maximum);
    const rawBody = String(document.body && document.body.innerText || '').slice(0, 120000);
    const body = compact(rawBody, 120000);
    const allImages = [...document.images]
      .map((image) => ({
        url: compact(image.currentSrc || image.src || image.getAttribute('data-src') || image.getAttribute('data-original'), 4000),
        width: Number(image.naturalWidth || image.width || 0),
        height: Number(image.naturalHeight || image.height || 0),
        alt: compact(image.alt, 240),
      }))
      .filter((image) => image.url.startsWith('http') && image.width >= 160 && image.height >= 100);
    const seenImages = new Set();
    const images = allImages.filter((image) => !seenImages.has(image.url) && seenImages.add(image.url)).slice(0, ${maxImages});
    const blocks = [...document.querySelectorAll('div,li,section,article')]
      .map((element) => String(element.innerText || '').trim())
      .filter((value) => value.includes('房') && /(￥|¥)\s*\d/.test(value) && value.length <= 1200);
    const seenBlocks = new Set();
    const offers = [];
    for (const block of blocks) {
      if (seenBlocks.has(block)) continue;
      seenBlocks.add(block);
      if (block.includes('登录看低价')) continue;
      const priceMatches = [...block.matchAll(/(?:￥|¥)\s*([0-9][0-9,]*)/g)].map((match) => Number(match[1].replace(/,/g, ''))).filter(Number.isFinite);
      const roomLines = block.split(/\n/).map((line) => compact(line, 240)).filter((line) => line.includes('房'));
      const roomType = roomLines.find((line) => /电竞|大床|双床|套房|房/.test(line)) || '';
      const availability = block.includes('已订完') ? 'sold_out' : (block.includes('可订') ? 'available' : 'unknown');
      const taxIncluded = block.includes('含税') ? true : (block.includes('不含税') || block.includes('另付税费') ? false : null);
      const cancellation = block.match(/(?:免费取消|不可取消|取消[^，。\n]{0,80})/)?.[0] || '';
      const workstationMatch = block.match(/(\d+)\s*台电竞电脑|5台及以上电竞电脑/);
      const workstations = workstationMatch ? (workstationMatch[0].startsWith('5台') ? 5 : Number(workstationMatch[1])) : null;
      if (roomType && workstations && priceMatches.length === 1 && availability === 'available' && taxIncluded !== null && cancellation) {
        offers.push({ room_type: roomType, workstations, nightly_price: priceMatches[0], availability, tax_included: taxIncluded, cancellation_policy: cancellation });
      }
    }
    const contextText = rawBody.replace(/\s+/g, '');
    return {
      title: document.title,
      has_login_price_gate: body.includes('登录看低价'),
      page_context_text: contextText.slice(0, 3000),
      room_type_names: [...new Set(rawBody.split(/\n/).map((line) => compact(line, 240)).filter((line) => line.includes('房') && /电竞|大床|双床|套房/.test(line)))].slice(0, 24),
      images,
      offers: offers.slice(0, 30),
    };
  })()`);
}

const raw = process.env.MARKET_EVIDENCE_REQUEST_JSON;
if (!raw) throw new Error("MARKET_EVIDENCE_REQUEST_JSON is required");
const request = JSON.parse(raw);
if (request.contract_version !== CONTRACT_VERSION) throw new Error("unsupported market evidence contract");
if (request.search?.provider_profile !== PROFILE) throw new Error(`Ego profile requires ${PROFILE}`);

const startedAt = now();
const pageSources = [];
const result = buildBaseResult(request, startedAt, pageSources);
const task = await useOrCreateTaskSpace(`market-evidence-${request.request_id || "ctrip"}`);
const inventory = Array.isArray(request.candidate_inventory) ? request.candidate_inventory : [];
const selected = inventory.filter((item) => item && item.benchmark_selected === true);
const candidates = inventory.map((item) => ({
  ...item.candidate,
  benchmark_selected: item.benchmark_selected === true,
  booking_evidence: item.ota_property ? [{ ...item.ota_property }] : [],
  room_offers: [],
}));
const candidateById = new Map(candidates.map((candidate) => [candidate.provider_place_id, candidate]));
const media = [];
const gaps = [];
let imageCount = 0;
let roomTypeCount = 0;
let pricedCandidateCount = 0;
let embeddedBytes = 0;

for (const item of selected) {
  const ota = item.ota_property;
  const candidate = candidateById.get(item.candidate.provider_place_id);
  if (!candidate || !ota) continue;
  const bookingUrl = ctripBookingUrl(ota, request.pricing_context);
  try {
    await openOrReuseTab(bookingUrl, { wait: true, timeout: 35 });
    await waitForNetworkIdle({ timeout: 10 }).catch(() => undefined);
    pageSources.push({ url: bookingUrl, status: 200 });
    const facts = await extractPageFacts(request.search.max_images_per_candidate);
    const observedAt = now();
    const checkoutDate = addNights(request.pricing_context.check_in_date, request.pricing_context.nights);
    const [, checkInMonth, checkInDay] = request.pricing_context.check_in_date.split('-').map(Number);
    const [, checkOutMonth, checkOutDay] = checkoutDate.split('-').map(Number);
    const requestedContextVisible = facts.page_context_text.includes(`${checkInMonth}月${checkInDay}日`)
      && facts.page_context_text.includes(`${checkOutMonth}月${checkOutDay}日`)
      && facts.page_context_text.includes(`${request.pricing_context.nights}晚`)
      && facts.page_context_text.includes(`${request.pricing_context.guests}成人`);
    candidate.booking_evidence = [{
      platform: ota.platform,
      property_id: ota.property_id,
      property_url: bookingUrl,
      match_method: ota.match_method,
      matched_at: ota.matched_at,
      observed_at: observedAt,
      page_title: text(facts.title, 300),
    }];
    roomTypeCount += Array.isArray(facts.room_type_names) ? facts.room_type_names.length : 0;
    const offers = Array.isArray(facts.offers) ? facts.offers : [];
    candidate.room_offers = (requestedContextVisible ? offers : []).map((offer, index) => ({
      room_type: text(offer.room_type, 240),
      room_type_provider_id: `${ota.property_id}:dom:${index + 1}`,
      workstations: Number(offer.workstations),
      nightly_price: Number(offer.nightly_price),
      availability: offer.availability,
      currency: "CNY",
      tax_included: offer.tax_included,
      cancellation_policy: text(offer.cancellation_policy, 240),
      pricing_context: request.pricing_context,
      source_url: bookingUrl,
      observed_at: observedAt,
    }));
    if (candidate.room_offers.length) pricedCandidateCount += 1;
    const images = [];
    for (const image of Array.isArray(facts.images) ? facts.images : []) {
      const collected = await fetchImage(image.url, pageSources, MAX_EMBEDDED_BYTES - embeddedBytes);
      if (!collected) continue;
      embeddedBytes += collected.bytes;
      images.push({
        caption: text(image.alt || "携程公开酒店/房型图（仅作视觉对标）", 240),
        data_uri: collected.data_uri,
        source_url: image.url,
        observed_at: observedAt,
        mime_type: collected.mime_type,
        sha256: collected.sha256,
      });
    }
    imageCount += images.length;
    if (images.length) {
      media.push({
        provider_place_id: candidate.provider_place_id,
        renovation_observation: "来源为已选竞品的 OTA 页面公开图片；用于装修、设备和空间感知对标，不代表拍摄日期或具体房号，仍须实勘复核。",
        observation_source_url: bookingUrl,
        images,
      });
    }
    if (facts.has_login_price_gate) {
      gaps.push(`${candidate.name || candidate.provider_place_id}：OTA 页面要求登录后展示同条件价格；请在 Ego Lite 登录后重试`);
    }
    if (!requestedContextVisible) {
      gaps.push(
        `${candidate.name || candidate.provider_place_id}：OTA 页面未确认请求报价条件（${request.pricing_context.check_in_date}、${request.pricing_context.nights}晚、${request.pricing_context.guests}成人）；不得读取价格`
      );
    }
  } catch (error) {
    pageSources.push({ url: bookingUrl, status: 599 });
    gaps.push(`${candidate.name || candidate.provider_place_id}：OTA 页面采集失败（${text(String(error), 240)}）`);
  }
}

if (!inventory.length) gaps.push("Ego OTA Profile requires candidate_inventory from the completed 2km map collection");
if (!selected.length && inventory.length) gaps.push("未选择任何价格/视觉标杆；请提供带 ota_property 的 benchmark_selected 候选");
if (request.required_evidence.room_types && roomTypeCount === 0) gaps.push("已选标杆未取得可追溯房型名称");
if (request.required_evidence.images && media.length < selected.length) gaps.push(`标杆图片未完整采集：${media.length}/${selected.length} 家`);
if (request.required_evidence.pricing && pricedCandidateCount < selected.length) gaps.push(`同条件可订报价未完整采集：${pricedCandidateCount}/${selected.length} 家`);

const complete = gaps.length === 0;
result.status = complete ? "complete" : "partial";
result.collector.finished_at = now();
result.coverage = {
  candidates: coverage(inventory.length ? "complete" : "failed", candidates.length),
  benchmark_set: coverage(selected.length ? "complete" : "failed", selected.length),
  room_types: coverage(roomTypeCount ? "complete" : "failed", roomTypeCount),
  images: coverage(media.length === selected.length && selected.length ? "complete" : "partial", imageCount),
  pricing: coverage(pricedCandidateCount === selected.length && selected.length ? "complete" : "partial", pricedCandidateCount),
};
result.collection_gaps = gaps;
result.competitor_analysis = {
  confirmed_location: request.target.center || null,
  collection_status: complete ? "complete" : "partial",
  pricing_context: request.pricing_context,
  candidates,
};
result.competitor_report = {
  title: `${request.target.name}：2km电竞竞品 OTA 报价与视觉证据`,
  candidate_media: media,
};
cliLog(JSON.stringify({ task_space_id: task.id, result }));

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

const CONTRACT_VERSION = "market-evidence-collection/v2";
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

function issue(code, message, retryable, providerPlaceId) {
  return {
    code,
    message: text(message, 500),
    retryable: Boolean(retryable),
    ...(providerPlaceId ? { provider_place_id: providerPlaceId } : {}),
  };
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
    collection_issues: [],
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
    const imageContext = (image) => [
      image.alt,
      image.className,
      image.parentElement && image.parentElement.className,
      image.parentElement && image.parentElement.parentElement && image.parentElement.parentElement.className,
    ].map((value) => String(value || '')).join(' ');
    const allImages = [...document.images]
      .map((image) => ({
        url: compact(image.currentSrc || image.src || image.getAttribute('data-src') || image.getAttribute('data-original'), 4000),
        width: Number(image.naturalWidth || image.width || 0),
        height: Number(image.naturalHeight || image.height || 0),
        alt: compact(image.alt, 240),
        context: imageContext(image),
      }))
      // Only use an explicitly hotel/room-gallery image. In particular, do not
      // let a logged-in account avatar become competitor visual evidence.
      .filter((image) => image.url.startsWith('http') && image.width >= 160 && image.height >= 100)
      .filter((image) => /photo\s*gallery|hotel\s*overview|酒店|房型|客房|room|gallery|album/i.test(image.context))
      .filter((image) => !/avatar|logo|qrcode|二维码/i.test(image.context));
    const seenImages = new Set();
    const images = allImages.filter((image) => !seenImages.has(image.url) && seenImages.add(image.url)).slice(0, ${maxImages});
    const roomPriceCards = [];
    const seenPriceCards = new Set();
    for (const card of [...document.querySelectorAll('div')]) {
      const classTokens = String(card.className || '').split(/\s+/);
      if (!classTokens.some((token) => /^commonRoomCard(?:Hidden)?__/.test(token))) continue;
      const raw = String(card.innerText || '').trim();
      if (!/(￥|¥)\s*\d/.test(raw) || !/预订|可订/.test(raw)) continue;
      const title = card.querySelector('[class*="commonRoomCard-title"], [role="button"]');
      const roomType = compact(title && title.innerText, 300);
      const prices = [...raw.matchAll(/(?:￥|¥)\s*([0-9][0-9,]*)/g)]
        .map((match) => Number(match[1].replace(/,/g, '')))
        .filter((value) => Number.isFinite(value) && value > 0);
      if (!roomType || !prices.length) continue;
      const key = roomType + '|' + prices.at(-1);
      if (seenPriceCards.has(key)) continue;
      seenPriceCards.add(key);
      roomPriceCards.push({
        room_type: roomType,
        display_price: prices.at(-1),
        availability: /已订完|售罄|满房|不可订/.test(raw) ? 'sold_out' : 'available',
        cancellation_policy: (raw.match(/(?:免费取消|不可取消|取消[^，。\n]{0,80})/) || [''])[0] || '',
        text: compact(raw, 1800),
      });
      if (roomPriceCards.length >= 30) break;
    }
    const contextText = rawBody.replace(/\s+/g, '');
    return {
      title: document.title,
      has_login_price_gate: body.includes('登录看低价'),
      page_context_text: contextText.slice(0, 3000),
      // A room-type observation must originate in a structured bookable-room
      // card.  Do not scrape arbitrary page prose: hotel features, summaries
      // and guest reviews often contain words such as “套房” or “电竞房”.
      room_type_names: [...new Set(roomPriceCards.map((card) => card.room_type))].slice(0, 30),
      images,
      room_price_cards: roomPriceCards,
    };
  })()`);
}

function pagePriceObservations(cards, pricingContext, sourceUrl, observedAt, propertyId) {
  const observations = [];
  const seen = new Set();
  for (const [index, card] of (Array.isArray(cards) ? cards : []).entries()) {
    const roomType = text(card && card.room_type, 300);
    const displayPrice = Number(card && card.display_price);
    if (!roomType || !Number.isFinite(displayPrice) || displayPrice <= 0) continue;
    const key = `${roomType}|${displayPrice}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const raw = text(card && card.text, 1_800);
    const workstations = (raw.match(/(\d+)\s*台(?:电竞)?(?:电脑|主机)/) || [])[1];
    const availability = card && card.availability === "sold_out" ? "sold_out" : "available";
    const cancellation = text(card && card.cancellation_policy, 240);
    const qualificationGaps = ["network_evidence_missing", "tax_scope_unknown"];
    if (availability !== "available") qualificationGaps.push("availability_not_confirmed");
    if (!cancellation) qualificationGaps.push("cancellation_policy_missing");
    if (!workstations) qualificationGaps.push("workstations_missing");
    observations.push({
      room_type: roomType,
      room_type_provider_id: `${propertyId}:ego-dom:${index + 1}`,
      price_type: "P1",
      display_price: displayPrice,
      currency: "CNY",
      availability,
      ...(cancellation ? { cancellation_policy: cancellation } : {}),
      pricing_context: pricingContext,
      source_url: sourceUrl,
      observed_at: observedAt,
      network_verified: false,
      dom_verified: true,
      price_match: false,
      adr_eligible: false,
      qualification_gaps: qualificationGaps,
      ...(workstations ? { workstations: Number(workstations) } : {}),
    });
  }
  return observations;
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
const collectionIssues = [];
let imageCount = 0;
let roomTypeCount = 0;
let pricedCandidateCount = 0;
let observedPriceCandidateCount = 0;
let noInventoryCandidateCount = 0;
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
    candidate.room_type_evidence = (Array.isArray(facts.room_type_names) ? facts.room_type_names : [])
      .map((roomType, index) => ({
        room_type: text(roomType, 300),
        room_type_provider_id: `${ota.property_id}:ego-dom:room-type:${index + 1}`,
        source_url: bookingUrl,
        observed_at: observedAt,
      }))
      .filter((item) => item.room_type);
    roomTypeCount += candidate.room_type_evidence.length;
    const pricingObservations = requestedContextVisible
      ? pagePriceObservations(
        facts.room_price_cards,
        request.pricing_context,
        bookingUrl,
        observedAt,
        ota.property_id,
      )
      : [];
    // P1 is an actual user-visible page price, but Ego intentionally does not
    // inspect Network payloads. Preserve it for reports/Feishu, never promote
    // it into ADR without the stricter P2 verifier.
    candidate.room_offers = [];
    candidate.pricing_observations = pricingObservations;
    if (candidate.room_offers.length) pricedCandidateCount += 1;
    if (pricingObservations.length) observedPriceCandidateCount += 1;
    const noInventory = /本酒店目前不接受预订|暂不接受预订|暂无可订房|当前无可订房型/.test(
      facts.page_context_text,
    );
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
      collectionIssues.push(issue(
        "AUTH_REQUIRED",
        "携程页面要求登录后才能展示同条件价格。",
        true,
        candidate.provider_place_id,
      ));
    }
    if (!requestedContextVisible) {
      gaps.push(
        `${candidate.name || candidate.provider_place_id}：OTA 页面未确认请求报价条件（${request.pricing_context.check_in_date}、${request.pricing_context.nights}晚、${request.pricing_context.guests}成人）；不得读取价格`
      );
      collectionIssues.push(issue(
        "QUERY_MISMATCH",
        "携程页面未展示与请求一致的入住日期、晚数和人数；不会使用页面价格。",
        true,
        candidate.provider_place_id,
      ));
    } else if (noInventory) {
      // An explicit no-booking state is a completed negative observation, not
      // a missing price. Keep ADR empty while allowing the collection receipt
      // to distinguish it from a selector/layout failure.
      noInventoryCandidateCount += 1;
      collectionIssues.push(issue(
        "NO_INVENTORY",
        "已在请求条件下确认该竞品目前不接受预订或无可订房型。",
        false,
        candidate.provider_place_id,
      ));
    } else if (!pricingObservations.length && !facts.has_login_price_gate) {
      collectionIssues.push(issue(
        "RATE_LOAD_TIMEOUT",
        "携程页面已回显报价条件，但未返回可识别的房型价格卡片。",
        true,
        candidate.provider_place_id,
      ));
    }
  } catch (error) {
    pageSources.push({ url: bookingUrl, status: 599 });
    gaps.push(`${candidate.name || candidate.provider_place_id}：OTA 页面采集失败（${text(String(error), 240)}）`);
    collectionIssues.push(issue(
      "RPA_FAILED",
      `携程页面采集失败：${text(String(error), 240)}`,
      true,
      candidate.provider_place_id,
    ));
  }
}

if (!inventory.length) gaps.push("Ego OTA Profile requires candidate_inventory from the completed 2km map collection");
if (!selected.length && inventory.length) gaps.push("未选择任何价格/视觉标杆；请提供带 ota_property 的 benchmark_selected 候选");
if (request.required_evidence.room_types && roomTypeCount === 0) gaps.push("已选标杆未取得可追溯房型名称");
if (request.required_evidence.images && media.length < selected.length) gaps.push(`标杆图片未完整采集：${media.length}/${selected.length} 家`);
const pricingResolvedCandidateCount = observedPriceCandidateCount + noInventoryCandidateCount;
if (request.required_evidence.pricing && pricingResolvedCandidateCount < selected.length) {
  gaps.push(`同条件页面价格观察或无房结论未完整采集：${pricingResolvedCandidateCount}/${selected.length} 家`);
}
if (observedPriceCandidateCount > 0 && pricedCandidateCount < observedPriceCandidateCount) {
  gaps.push("已保存携程 P1 页面价格观察；缺少 Network 双证据、税费口径或机位数，暂不得计入 ADR。");
}

const complete = gaps.length === 0;
result.status = complete ? "complete" : "partial";
result.collector.finished_at = now();
result.coverage = {
  candidates: coverage(inventory.length ? "complete" : "failed", candidates.length),
  benchmark_set: coverage(selected.length ? "complete" : "failed", selected.length),
  room_types: coverage(roomTypeCount ? "complete" : "failed", roomTypeCount),
  images: coverage(media.length === selected.length && selected.length ? "complete" : "partial", imageCount),
  pricing: coverage(
    noInventoryCandidateCount === selected.length && selected.length ? "complete" : "partial",
    pricingResolvedCandidateCount,
    noInventoryCandidateCount
      ? "包含已确认无可订房型的负向价格结果；不会生成 ADR"
      : (observedPriceCandidateCount > pricedCandidateCount ? "包含仅展示、未进入 ADR 的 P1 页面价格观察" : undefined),
  ),
};
result.collection_gaps = gaps;
result.collection_issues = collectionIssues;
// The incoming inventory is the already bounded 2km map pool.  A full pool
// remains a completed spatial analysis even if live OTA rates are partial or
// only P1; this preserves valid competitor and visual research while the ADR
// gate continues to require P2 room offers.
// Do not infer completeness from a local count: an exactly-200-property map
// response can still be complete. The preceding map Profile has already
// proved this pool and the contract requires us to echo it verbatim.
const spatialCollectionComplete = request.candidate_pool?.status === "complete";
result.competitor_analysis = {
  confirmed_location: request.target.center || null,
  collection_status: spatialCollectionComplete ? "complete" : "partial",
  pricing_context: request.pricing_context,
  candidates,
};
result.spatial_collection = request.candidate_pool;
result.competitor_report = {
  title: `${request.target.name}：2km电竞竞品 OTA 报价与视觉证据`,
  candidate_media: media,
};
cliLog(JSON.stringify({ task_space_id: task.id, result }));

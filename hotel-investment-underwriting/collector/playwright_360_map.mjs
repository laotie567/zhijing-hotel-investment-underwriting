#!/usr/bin/env node
/**
 * Browser-page implementation of market-evidence-collection/v2.
 *
 * This is intentionally a narrow, versioned 360 Map profile.  It opens every
 * JSON/image URL through Playwright's browser context and returns source URLs,
 * status codes, timestamps and bounded evidence.  It does not manufacture a
 * booking quote: 360's broad listing price is not a same-date room offer.
 */

import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

const CONTRACT_VERSION = "market-evidence-collection/v2";
const PROFILE = "360-map-v1";
const PROVIDER = "360地图";
const PAGE_SIZE = 30;
const MAX_BENCHMARK_CANDIDATES = 8;
const EARTH_RADIUS_METERS = 6_371_000;
const MAX_EMBEDDED_BYTES = 7_500_000;
const USER_AGENT = "Mozilla/5.0 (compatible; ZhijingMarketEvidence/1.0)";

function now() {
  return new Date().toISOString();
}

function compactText(value, maximum = 2_000) {
  if (typeof value !== "string") return "";
  return value.replace(/\s+/g, " ").trim().slice(0, maximum);
}

function normal(value) {
  return compactText(value, 1_000)
    .toLowerCase()
    .replace(/[\s\-—_（）()【】\[\]·]/g, "");
}

function haversineMeters(longitudeA, latitudeA, longitudeB, latitudeB) {
  const latitudeDelta = ((latitudeB - latitudeA) * Math.PI) / 180;
  const longitudeDelta = ((longitudeB - longitudeA) * Math.PI) / 180;
  const startLatitude = (latitudeA * Math.PI) / 180;
  const endLatitude = (latitudeB * Math.PI) / 180;
  const a =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(startLatitude) * Math.cos(endLatitude) * Math.sin(longitudeDelta / 2) ** 2;
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.sqrt(a));
}

function sourceUrl(placeId) {
  return `https://m.map.360.cn/m/search/detail/pid=${encodeURIComponent(placeId)}`;
}

function searchUrl({ keyword, cityId, center, radiusMeters, batch }) {
  const parameters = new URLSearchParams({
    keyword,
    batch: String(batch),
    number: String(PAGE_SIZE),
    sid: "1002",
    mobile: "1",
    scheme: "https",
    cityid: cityId,
  });
  if (center) {
    parameters.set("cenX", String(center.longitude));
    parameters.set("cenY", String(center.latitude));
    parameters.set("range", String(radiusMeters));
  }
  return `https://restapi.map.360.cn/api/simple?${parameters.toString()}`;
}

function asImageDataUri(bytes, contentType) {
  let kind = null;
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) kind = "jpeg";
  else if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47
  ) {
    kind = "png";
  } else if (
    bytes.length >= 12 &&
    bytes.subarray(0, 4).toString() === "RIFF" &&
    bytes.subarray(8, 12).toString() === "WEBP"
  ) {
    kind = "webp";
  } else if (typeof contentType === "string") {
    const matched = contentType.match(/^image\/(jpeg|png|webp)/i);
    kind = matched?.[1]?.toLowerCase() ?? null;
  }
  return kind ? `data:image/${kind};base64,${bytes.toString("base64")}` : null;
}

function coverage(status, observedCount, notes) {
  const result = { status, observed_count: observedCount };
  if (notes) result.notes = notes;
  return result;
}

function candidateIdsSha256(candidates) {
  const identifiers = candidates
    .map((candidate) => String(candidate?.provider_place_id || ""))
    .sort();
  return createHash("sha256").update(JSON.stringify(identifiers), "utf8").digest("hex");
}

function baseResult({ request, startedAt, engineVersion, pageSources }) {
  return {
    contract_version: CONTRACT_VERSION,
    ...(request.request_id ? { request_id: request.request_id } : {}),
    status: "failed",
    collector: {
      engine: "playwright",
      engine_version: engineVersion,
      source_profile: PROFILE,
      started_at: startedAt,
      finished_at: now(),
      page_sources: pageSources,
    },
    target_resolution: null,
    coverage: {
      candidates: coverage("failed", 0),
      benchmark_set: coverage("failed", 0),
      room_types: coverage("failed", 0),
      images: coverage("failed", 0),
      pricing: coverage("failed", 0),
    },
    collection_gaps: [],
    competitor_analysis: { collection_status: "partial", candidates: [] },
    competitor_report: { candidate_media: [] },
  };
}

function candidateScore(candidate, target) {
  const candidateName = normal(candidate?.name);
  const expectedName = normal(target.name);
  const candidateAddress = normal(candidate?.address || candidate?.detail?.address || "");
  const expectedAddress = normal(target.address);
  let score = 0;
  if (candidateName === expectedName) score += 100;
  else if (candidateName.includes(expectedName) || expectedName.includes(candidateName)) score += 60;
  if (candidateAddress && expectedAddress && (candidateAddress.includes(expectedAddress) || expectedAddress.includes(candidateAddress))) score += 100;
  const addressTokens = compactText(target.address, 500)
    .split(/[，,\s]/)
    .map(normal)
    .filter((item) => item.length >= 2);
  score += addressTokens.filter((item) => candidateAddress.includes(item)).length * 15;
  return score;
}

function candidateCenter(item) {
  if (
    !item ||
    typeof item.pguid !== "string" ||
    !Number.isFinite(item.x) ||
    !Number.isFinite(item.y)
  ) {
    return null;
  }
  return {
    provider: PROVIDER,
    provider_place_id: item.pguid,
    coordinate_system: "GCJ-02",
    longitude: Number(item.x),
    latitude: Number(item.y),
    status: "auto_confirmed_exact",
  };
}

function resolveTarget(items, target) {
  const scored = items
    .map((item) => ({ item, score: candidateScore(item, target) }))
    .filter(({ item }) => candidateCenter(item))
    .sort((left, right) => right.score - left.score);
  if (!scored.length) return { center: null, gap: "目标物业未在页面检索结果中找到" };
  const [first, second] = scored;
  // Address may be abbreviated by the page.  Do not pretend that two similarly
  // named hotels are an exact match: a caller must send target.center then retry.
  if (first.score < 60 || (second && first.score === second.score)) {
    return {
      center: null,
      gap: "目标物业页面检索存在歧义；请确认同源 provider_place_id 与 GCJ-02 中心点后重试",
    };
  }
  return { center: candidateCenter(first.item), gap: null };
}

function roomTypeNames(detail) {
  if (!Array.isArray(detail?.room_types)) return [];
  return detail.room_types
    .map((item) => compactText(item?.name, 180))
    .filter(Boolean)
    .slice(0, 12);
}

function firstRoomPhoto(detail) {
  if (!Array.isArray(detail?.room_types)) return null;
  for (const roomType of detail.room_types) {
    if (!roomType || !Array.isArray(roomType.imgs)) continue;
    const imageUrl = roomType.imgs.find((value) => typeof value === "string" && value.startsWith("https://"));
    if (imageUrl) {
      const name = compactText(roomType.name, 180) || "公开房型图";
      return { imageUrl, caption: `公开房型图：${name}` };
    }
  }
  return null;
}

function reviewCount(item) {
  const value = item?.detail?.review_count ?? item?.review_count ?? item?.comment_num;
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function benchmarkCandidates(candidates, requestedMaximum) {
  // Choose a bounded, repeatable high-quality set within the intact 2km pool.
  // This ranking only decides which at-most-eight candidates receive costly
  // OTA room/photo research. It prefers a public room photo, room-type
  // disclosure, rating/review signal and then shorter distance. Provider ID is
  // the last tie-breaker, keeping a repeat run deterministic.
  const requested = Number(requestedMaximum);
  const maximum = Number.isInteger(requested)
    ? Math.min(Math.max(requested, 0), MAX_BENCHMARK_CANDIDATES)
    : MAX_BENCHMARK_CANDIDATES;
  return [...candidates]
    .sort((left, right) => {
      const leftPhoto = firstRoomPhoto(left.item.detail) ? 1 : 0;
      const rightPhoto = firstRoomPhoto(right.item.detail) ? 1 : 0;
      if (rightPhoto !== leftPhoto) return rightPhoto - leftPhoto;
      const leftRooms = roomTypeNames(left.item.detail).length;
      const rightRooms = roomTypeNames(right.item.detail).length;
      if (rightRooms !== leftRooms) return rightRooms - leftRooms;
      const leftRating = Number.isFinite(left.item.avg_rating) ? Number(left.item.avg_rating) : 0;
      const rightRating = Number.isFinite(right.item.avg_rating) ? Number(right.item.avg_rating) : 0;
      if (rightRating !== leftRating) return rightRating - leftRating;
      const leftReviews = reviewCount(left.item);
      const rightReviews = reviewCount(right.item);
      if (rightReviews !== leftReviews) return rightReviews - leftReviews;
      if (left.distance !== right.distance) return left.distance - right.distance;
      return String(left.item.pguid).localeCompare(String(right.item.pguid), "zh-CN");
    })
    .slice(0, maximum);
}

function benchmarkSelectionReason(candidate) {
  // Persist the fixed evidence order that led to a costly OTA/visual deep
  // research slot. It is an explanation of the deterministic selection, not
  // a quality claim inferred by a model.
  const parts = [];
  if (firstRoomPhoto(candidate.item?.detail)) parts.push("有公开房型图");
  const roomTypes = roomTypeNames(candidate.item?.detail).length;
  if (roomTypes) parts.push(`披露${roomTypes}个房型`);
  const rating = Number(candidate.item?.avg_rating);
  if (Number.isFinite(rating) && rating > 0) parts.push(`评分${rating}`);
  const reviews = reviewCount(candidate.item);
  if (reviews) parts.push(`${reviews}条点评`);
  parts.push(`距目标${Math.round(candidate.distance)}米`);
  return `固定标杆排序：${parts.join("；")}`;
}

function candidateProvider(center) {
  // Classification compares a candidate with the confirmed 2km centre by
  // provider identity. `360地图` is only a display label, so reuse the actual
  // centre identity and keep automatic/manual centre confirmation consistent.
  return center.provider;
}

function hasPrimaryEsportsLodgingIdentity(item) {
  // A generic hotel whose title merely mentions an esports room is not a
  // primary-esports hotel. The page must identify the accommodation itself as
  // 电竞酒店/电竞民宿/电竞客栈 (or the provider's category must do so).
  const name = compactText(item?.name, 300);
  const category = compactText(item?.cat_new_name, 120);
  const detailText = compactText(
    [item?.detail?.category, item?.detail?.theme, ...(Array.isArray(item?.detail?.themes) ? item.detail.themes : [])]
      .filter(Boolean)
      .join(" "),
    1_000,
  );
  return /电竞(?:酒店|民宿|客栈|公寓|旅店)/.test(name)
    || /电竞(?:酒店|民宿|客栈|住宿)/.test(`${category} ${detailText}`);
}

function operatingStatusFromListing(item) {
  // A current POI search result is the minimum operating signal. An explicit
  // closure marker always wins and is retained as an excluded candidate.
  const statusText = compactText(
    [item?.status, item?.business_status, item?.detail?.status, item?.detail?.business_status]
      .filter(Boolean)
      .join(" "),
    500,
  );
  return /歇业|停业|关闭|closed/i.test(statusText) ? "closed" : "operating";
}

function profile(item, detail) {
  const roomTypes = roomTypeNames(detail);
  const features = [
    ...(Array.isArray(detail?.themes)
      ? detail.themes.map((item) => compactText(item, 120)).filter(Boolean)
      : []),
    roomTypes.length ? `公开房型：${roomTypes.join("；")}` : "",
  ]
    .filter(Boolean)
    .join("；")
    .slice(0, 2_000);
  const result = {
    opening_or_renovation: "页面公开资料未核验装修日期；须以实勘和经营方资料复核。",
    image_quality: "页面聚合展示的公开房型图；仅作装修、设备和空间感知参考。",
    features,
    surroundings: compactText(item?.address, 2_000),
  };
  if (Number.isFinite(item?.avg_rating) && item.avg_rating >= 0 && item.avg_rating <= 5) result.rating = item.avg_rating;
  if (Number.isInteger(detail?.review_count) && detail.review_count >= 0) result.review_count = detail.review_count;
  return Object.fromEntries(Object.entries(result).filter(([, value]) => value !== ""));
}

async function main() {
  const input = await new Promise((resolve, reject) => {
    let body = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (body += chunk));
    process.stdin.on("end", () => {
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
  });
  if (input?.contract_version !== CONTRACT_VERSION) throw new Error("unsupported market evidence contract");
  if (input?.search?.provider_profile !== PROFILE) {
    throw new Error(`Playwright profile requires ${PROFILE}`);
  }
  const startedAt = now();
  const pageSources = [];
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ userAgent: USER_AGENT, locale: "zh-CN" });
    const page = await context.newPage();
    const engineVersion = `${await browser.version()}`;
    const result = baseResult({ request: input, startedAt, engineVersion, pageSources });
    const fetchJson = async (url) => {
      const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30_000 });
      const status = response?.status() ?? 599;
      pageSources.push({ url, status });
      if (!response || !response.ok()) throw new Error(`page source returned HTTP ${status}: ${url}`);
      const body = await page.locator("body").innerText({ timeout: 5_000 });
      const parsed = JSON.parse(body);
      if (!parsed || typeof parsed !== "object") throw new Error(`page source did not return JSON: ${url}`);
      return parsed;
    };

    let center = input.target.center ?? null;
    if (!center) {
      const targetSearch = await fetchJson(
        searchUrl({ keyword: input.target.name, cityId: input.target.city_id, batch: 1 })
      );
      const targetItems = Array.isArray(targetSearch.poi) ? targetSearch.poi : [];
      const resolved = resolveTarget(targetItems, input.target);
      if (!resolved.center) {
        result.collector.finished_at = now();
        result.collection_gaps = [resolved.gap];
        result.competitor_analysis = { collection_status: "partial", candidates: [] };
        process.stdout.write(JSON.stringify(result));
        return;
      }
      center = resolved.center;
    }
    result.target_resolution = center;

    const firstPage = await fetchJson(
      searchUrl({
        keyword: input.search.query,
        cityId: input.target.city_id,
        center,
        radiusMeters: input.search.radius_meters,
        batch: 1,
      })
    );
    const hasKnownTotal = Number.isInteger(firstPage.totalcount) && firstPage.totalcount >= 0;
    const total = hasKnownTotal ? firstPage.totalcount : 0;
    // Without an explicit total the page cannot prove that pagination ended;
    // preserve the first-page facts but never call the 2km population complete.
    const sourceSetTruncated = !hasKnownTotal || total > input.search.max_candidates;
    const pageCount = hasKnownTotal
      ? Math.min(Math.ceil(total / PAGE_SIZE), Math.ceil(input.search.max_candidates / PAGE_SIZE))
      : 1;
    const pages = [firstPage];
    for (let batch = 2; batch <= pageCount; batch += 1) {
      pages.push(
        await fetchJson(
          searchUrl({
            keyword: input.search.query,
            cityId: input.target.city_id,
            center,
            radiusMeters: input.search.radius_meters,
            batch,
          })
        )
      );
    }
    const byId = new Map();
    for (const sourcePage of pages) {
      for (const item of Array.isArray(sourcePage.poi) ? sourcePage.poi : []) {
        if (typeof item?.pguid === "string") byId.set(item.pguid, item);
      }
    }
    const observedAt = now();
    const candidates = [...byId.values()]
      .filter((item) => item.pguid !== center.provider_place_id)
      .filter((item) => hasPrimaryEsportsLodgingIdentity(item))
      .filter((item) => ["酒店", "客栈民宿", "住宿服务"].includes(item?.cat_new_name))
      .map((item) => ({
        item,
        distance: haversineMeters(center.longitude, center.latitude, Number(item.x), Number(item.y)),
      }))
      .filter(({ item, distance }) => Number.isFinite(item?.x) && Number.isFinite(item?.y) && distance <= input.search.radius_meters)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, input.search.max_candidates);

    const selectedBenchmarks = benchmarkCandidates(
      candidates,
      input.search.max_benchmark_candidates,
    );
    const benchmarkMetadata = new Map(selectedBenchmarks.map((candidate, index) => [
      candidate.item.pguid,
      { rank: index + 1, reason: benchmarkSelectionReason(candidate) },
    ]));
    const benchmarkCandidateIds = new Set(benchmarkMetadata.keys());
    const formalCandidates = candidates.map(({ item }) => ({
      provider: candidateProvider(center),
      provider_place_id: item.pguid,
      name: compactText(item.name, 300),
      coordinate_system: "GCJ-02",
      longitude: Number(item.x),
      latitude: Number(item.y),
      property_kind: "lodging",
      esports_positioning: "primary",
      operating_status: operatingStatusFromListing(item),
      source: {
        source_platform: "360地图页面（聚合公开酒店资料）",
        source_url: sourceUrl(item.pguid),
        observed_at: observedAt,
        confidence: "medium",
      },
      benchmark_selected: benchmarkCandidateIds.has(item.pguid),
      ...(benchmarkMetadata.has(item.pguid) ? {
        benchmark_rank: benchmarkMetadata.get(item.pguid).rank,
        benchmark_selection_reason: benchmarkMetadata.get(item.pguid).reason,
      } : {}),
      room_offers: [],
      market_profile: profile(item, item.detail),
    }));

    let embeddedBytes = 0;
    const candidateMedia = [];
    for (const { item } of candidates) {
      if (!benchmarkCandidateIds.has(item.pguid)) continue;
      const photo = firstRoomPhoto(item.detail);
      if (!photo || input.search.max_images_per_candidate === 0) continue;
      try {
        const response = await context.request.get(photo.imageUrl, { timeout: 20_000 });
        pageSources.push({ url: photo.imageUrl, status: response.status() });
        if (!response.ok()) continue;
        const bytes = Buffer.from(await response.body());
        if (embeddedBytes + bytes.length > MAX_EMBEDDED_BYTES) continue;
        const dataUri = asImageDataUri(bytes, response.headers()["content-type"]);
        if (!dataUri) continue;
        embeddedBytes += bytes.length;
        candidateMedia.push({
          provider_place_id: item.pguid,
          renovation_observation:
            "来源为页面聚合展示的公开房型图；仅作装修、设备和空间感知的内部对标，不代表拍摄日期、具体房号或当前经营状态，须以实勘复核。",
          observation_source_url: sourceUrl(item.pguid),
          images: [
            {
              caption: `${photo.caption}（仅作内部视觉对标）`,
              data_uri: dataUri,
              source_url: photo.imageUrl,
            },
          ],
        });
      } catch {
        // Preserve the candidate and return an explicit coverage gap below.
      }
    }

    const roomTypeCount = candidates.reduce(
      (count, { item }) => count + roomTypeNames(item.detail).length,
      0
    );
    const required = input.required_evidence;
    const gaps = [];
    if (!hasKnownTotal) {
      gaps.push("页面查询未返回总数；无法证明已穷尽 2km 候选分页");
    } else if (sourceSetTruncated) {
      gaps.push(`页面查询结果超过 ${input.search.max_candidates} 家上限；2km候选集未完整收集`);
    }
    const benchmarkCandidateCount = benchmarkCandidateIds.size;
    if (required.benchmark_set && benchmarkCandidateCount === 0 && candidates.length > 0) {
      gaps.push("未形成价格/视觉标杆集；请提高 max_benchmark_candidates 后重试");
    }
    if (required.images && candidateMedia.length < benchmarkCandidateCount) {
      gaps.push(`竞品图片未覆盖全部已选标杆：已取得 ${candidateMedia.length}/${benchmarkCandidateCount} 家`);
    }
    if (required.room_types && roomTypeCount === 0) gaps.push("页面未取得可追溯的竞品房型名称");
    // This profile deliberately has no booking checkout flow.  It may complete
    // the 2km candidate pool, but can never complete the end-to-end evidence
    // set by itself: an OTA profile must supply the shared-context room quotes.
    // Keep this gap even when pricing is not requested in this invocation so
    // `status=complete` never contradicts `coverage.pricing=not_collected`.
    gaps.push("360 地图已完成 2km 候选池；同条件房态与报价须由 OTA Profile 补齐，当前不得生成竞品 ADR 建议");
    const complete = gaps.length === 0;
    result.status = complete ? "complete" : "partial";
    result.collector.finished_at = now();
    result.coverage = {
      candidates: coverage(sourceSetTruncated ? "partial" : "complete", formalCandidates.length),
      benchmark_set: coverage(
        benchmarkCandidateCount > 0 || candidates.length === 0 ? "complete" : "failed",
        benchmarkCandidateCount
      ),
      room_types: coverage(roomTypeCount ? "complete" : "failed", roomTypeCount),
      images: coverage(
        candidateMedia.length === benchmarkCandidateCount ? "complete" : "partial",
        candidateMedia.length
      ),
      pricing: coverage("not_collected", 0, "360 Map broad listing data is not a same-context room quote"),
    };
    result.collection_gaps = gaps;
    // Spatial classification is complete once the entire bounded 2km pool has
    // been enumerated. Price collection is a separate downstream OTA concern;
    // it must not erase valid location/competitor evidence.
    const spatialCollectionComplete = !sourceSetTruncated;
    result.competitor_analysis = {
      confirmed_location: center,
      collection_status: spatialCollectionComplete ? "complete" : "partial",
      pricing_context: input.pricing_context,
      candidates: formalCandidates,
    };
    result.spatial_collection = {
      status: spatialCollectionComplete ? "complete" : "partial",
      source_engine: "playwright",
      source_profile: "360-map-v1",
      center,
      candidate_count: formalCandidates.length,
      candidate_ids_sha256: candidateIdsSha256(formalCandidates),
    };
    result.competitor_report = {
      title: `${input.target.name}：2km纯电竞竞品页面调研`,
      candidate_media: candidateMedia,
    };
    process.stdout.write(JSON.stringify(result));
  } finally {
    if (browser) await browser.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error?.stack || error}\n`);
    process.exitCode = 2;
  });
}

export {
  benchmarkCandidates,
  benchmarkSelectionReason,
  candidateIdsSha256,
  candidateProvider,
  firstRoomPhoto,
  hasPrimaryEsportsLodgingIdentity,
  roomTypeNames,
};

#!/usr/bin/env node
/**
 * Browser-page implementation of market-evidence-collection/v1.
 *
 * This is intentionally a narrow, versioned 360 Map profile.  It opens every
 * JSON/image URL through Playwright's browser context and returns source URLs,
 * status codes, timestamps and bounded evidence.  It does not manufacture a
 * booking quote: 360's broad listing price is not a same-date room offer.
 */

import { chromium } from "playwright";

const CONTRACT_VERSION = "market-evidence-collection/v1";
const PROFILE = "360-map-v1";
const PROVIDER = "360地图";
const PAGE_SIZE = 30;
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
    const total = Number.isInteger(firstPage.totalcount) && firstPage.totalcount > 0 ? firstPage.totalcount : 0;
    const sourceSetTruncated = total > input.search.max_candidates;
    const pageCount = Math.min(Math.ceil(total / PAGE_SIZE), Math.ceil(input.search.max_candidates / PAGE_SIZE));
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
      .filter((item) => typeof item?.name === "string" && item.name.includes("电竞"))
      .filter((item) => ["酒店", "客栈民宿", "住宿服务"].includes(item?.cat_new_name))
      .map((item) => ({
        item,
        distance: haversineMeters(center.longitude, center.latitude, Number(item.x), Number(item.y)),
      }))
      .filter(({ item, distance }) => Number.isFinite(item?.x) && Number.isFinite(item?.y) && distance <= input.search.radius_meters)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, input.search.max_candidates);

    const benchmarkCandidateIds = new Set(
      candidates.slice(0, input.search.max_benchmark_candidates).map(({ item }) => item.pguid)
    );
    const formalCandidates = candidates.map(({ item }) => ({
      provider: PROVIDER,
      provider_place_id: item.pguid,
      name: compactText(item.name, 300),
      coordinate_system: "GCJ-02",
      longitude: Number(item.x),
      latitude: Number(item.y),
      property_kind: "lodging",
      esports_positioning: "primary",
      operating_status: "operating",
      source: {
        source_platform: "360地图页面（聚合公开酒店资料）",
        source_url: sourceUrl(item.pguid),
        observed_at: observedAt,
        confidence: "medium",
      },
      benchmark_selected: benchmarkCandidateIds.has(item.pguid),
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
    if (sourceSetTruncated) {
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
    // This profile deliberately has no booking checkout flow.  A price profile
    // must use the exact shared date/night/guest context before emitting offers.
    if (required.pricing) gaps.push("当前页面来源未完成同条件房态与报价采集；不得生成竞品 ADR 建议");
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
    result.competitor_analysis = {
      confirmed_location: center,
      collection_status: complete ? "complete" : "partial",
      pricing_context: input.pricing_context,
      candidates: formalCandidates,
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

main().catch((error) => {
  process.stderr.write(`${error?.stack || error}\n`);
  process.exitCode = 2;
});

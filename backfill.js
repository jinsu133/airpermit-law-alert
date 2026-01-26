// backfill.js
const fs = require('fs');
const path = require('path');

const PUBLIC_DIR = path.join(__dirname, 'public');
if (!fs.existsSync(PUBLIC_DIR)) fs.mkdirSync(PUBLIC_DIR, { recursive: true });
const CHANGELOG_PATH = path.join(PUBLIC_DIR, 'changelog.json');

const LAW_DRF_BASE = "http://www.law.go.kr/DRF";
const LAW_OC = process.env.LAW_OC;

const LAW_NAMES = [
  "대기환경보전법", "대기환경보전법 시행령", "대기환경보전법 시행규칙",
  "환경분야 시험·검사 등에 관한 법률", "환경분야 시험·검사 등에 관한 법률 시행령", "환경분야 시험·검사 등에 관한 법률 시행규칙",
  "대기관리권역의 대기환경개선에 관한 특별법", "대기관리권역의 대기환경개선에 관한 특별법 시행령", "대기관리권역의 대기환경개선에 관한 특별법 시행규칙",
  "환경오염시설의 통합관리에 관한 법률", "환경오염시설의 통합관리에 관한 법률 시행령", "환경오염시설의 통합관리에 관한 법률 시행규칙",
];
const ADMRUL_QUERIES = ["대기오염공정시험기준"];

async function fetchWithTimeout(url, options = {}, timeout = 60000) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);
    const response = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(id);
    return response;
}

async function fetchAllLawVersions(lawName) {
    const allVersions = [];
    const params = new URLSearchParams({ OC: LAW_OC, target: "law", type: "JSON", query: lawName, display: "100", sort: "ddes" });
    const url = `${LAW_DRF_BASE}/lawSearch.do?${params.toString()}`;
    try {
        const r = await fetchWithTimeout(url);
        if (!r.ok) throw new Error(`HTTP error! status: ${r.status}`);
        const data = await r.json();
        const items = data.LawSearch?.law ? (Array.isArray(data.LawSearch.law) ? data.LawSearch.law : [data.LawSearch.law]) : [];
        for (const it of items) {
            const dateStr = it["공포일자"] || "19000101";
            if (parseInt(dateStr) >= 20200101) {
                allVersions.push({
                    status: "MOD", kind: "법령", title: it["법령명한글"], date: it["공포일자"],
                    id: it["법령ID"], diff_url: null,
                    detected_at_utc: `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}T00:00:00Z`
                });
            }
        }
    } catch (e) { console.warn(`[WARN] Law fetch failed for ${lawName}: ${e}`); } 
    return allVersions;
}

async function fetchAllAdmrulVersions(query) {
    const allVersions = [];
    const params = new URLSearchParams({ OC: LAW_OC, target: "admrul", type: "JSON", query: query, display: "100", sort: "ddes" });
    const url = `${LAW_DRF_BASE}/lawService.do?${params.toString()}`;
    try {
        const r = await fetchWithTimeout(url);
        if (!r.ok) throw new Error(`HTTP error! status: ${r.status}`);
        const data = await r.json();
        const items = data.admrul ? (Array.isArray(data.admrul) ? data.admrul : [data.admrul]) : [];
        for (const it of items) {
            const dateStr = it["공포일자"] || "19000101";
            if (parseInt(dateStr) >= 20200101) {
                allVersions.push({
                    status: "MOD", kind: "고시", title: it["행정규칙명"], date: it["공포일자"],
                    id: it["행정규칙ID"], diff_url: null,
                    detected_at_utc: `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}T00:00:00Z`
                });
            }
        }
    } catch (e) { console.warn(`[WARN] Admrul fetch failed for ${query}: ${e}`); } 
    return allVersions;
}

async function main() {
    if (!LAW_OC) {
        console.error("[ERROR] LAW_OC env var is not set.");
        return;
    }
    console.log("Starting backfill with updated law & admrul list...");
    let historicalItems = [];

    for (const name of LAW_NAMES) {
        console.log(`Fetching law: ${name}...`);
        const versions = await fetchAllLawVersions(name);
        historicalItems.push(...versions);
        console.log(`  > Found ${versions.length} versions.`);
    }
    for (const query of ADMRUL_QUERIES) {
        console.log(`Fetching admrul: ${query}...`);
        const versions = await fetchAllAdmrulVersions(query);
        historicalItems.push(...versions);
        console.log(`  > Found ${versions.length} versions.`);
    }

    let existingItems = [];
    if (fs.existsSync(CHANGELOG_PATH)) {
        try {
            existingItems = JSON.parse(fs.readFileSync(CHANGELOG_PATH, 'utf-8')).items || [];
        } catch { console.warn("Could not parse existing changelog."); } 
    }
    console.log(`Loaded ${existingItems.length} existing items.`);

    const mergedItems = new Map();
    for (const item of [...historicalItems, ...existingItems]) {
        const key = `${item.id}-${item.date}`;
        if (!mergedItems.has(key)) mergedItems.set(key, item);
    }
    
    const finalItems = Array.from(mergedItems.values()).sort((a, b) => b.detected_at_utc.localeCompare(a.detected_at_utc));
    fs.writeFileSync(CHANGELOG_PATH, JSON.stringify({ items: finalItems }, null, 2), 'utf-8');
    console.log(`\nBackfill complete. Total ${finalItems.length} items saved.`);
}

main();

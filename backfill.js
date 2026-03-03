// backfill.js
const fs = require('fs');
const path = require('path');

const PUBLIC_DIR = path.join(__dirname, 'public');
if (!fs.existsSync(PUBLIC_DIR)) fs.mkdirSync(PUBLIC_DIR, { recursive: true });
const CHANGELOG_PATH = path.join(PUBLIC_DIR, 'changelog.json');

const LAW_DRF_BASE = "http://www.law.go.kr/DRF";
const ASSEMBLY_BASE = "https://open.assembly.go.kr/portal/openapi";
const LAW_OC = process.env.LAW_OC;
const ASSEMBLY_KEY = process.env.ASSEMBLY_KEY;

const LAW_NAMES = [
  "대기환경보전법","대기환경보전법 시행령","대기환경보전법 시행규칙", "환경분야 시험·검사 등에 관한 법률","환경분야 시험·검사 등에 관한 법률 시행령","환경분야 시험·검사 등에 관한 법률 시행규칙",
  "대기관리권역의 대기환경개선에 관한 특별법","대기관리권역의 대기환경개선에 관한 특별법 시행령","대기관리권역의 대기환경개선에 관한 특별법 시행규칙",
  "환경오염시설의 통합관리에 관한 법률","환경오염시설의 통합관리에 관한 법률 시행령","환경오염시설의 통합관리에 관한 법률 시행규칙",
];
const ADMRUL_QUERIES = ["대기오염공정시험기준"];
const BILL_KEYWORDS = ["대기환경보전법", "환경분야 시험·검사 등에 관한 법률", "대기관리권역", "환경오염시설 통합관리"];

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
    try {
        const r = await fetchWithTimeout(`${LAW_DRF_BASE}/lawSearch.do?${params.toString()}`);
        if (!r.ok) throw new Error(`HTTP error! status: ${r.status}`);
        const data = await r.json();
        const items = data.LawSearch?.law ? (Array.isArray(data.LawSearch.law) ? data.LawSearch.law : [data.LawSearch.law]) : [];
        for (const it of items) {
            const dateStr = it["공포일자"] || "19000101";
            if (parseInt(dateStr) >= 20200101) {
                allVersions.push({ status: "MOD", kind: "법령", title: it["법령명한글"], date: dateStr, id: it["법령ID"], diff_url: null, detected_at_utc: `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}T00:00:00Z` });
            }
        }
    } catch (e) { console.warn(`[WARN] Law fetch failed for ${lawName}: ${e.message}`); } 
    return allVersions;
}

async function fetchAllAdmrulVersions(query) {
    const allVersions = [];
    const params = new URLSearchParams({ OC: LAW_OC, target: "admrul", type: "JSON", query: query, display: "100", sort: "ddes" });
    try {
        const r = await fetchWithTimeout(`${LAW_DRF_BASE}/lawService.do?${params.toString()}`);
        if (!r.ok) throw new Error(`HTTP error! status: ${r.status}`);
        const data = await r.json();
        const items = data.admrul ? (Array.isArray(data.admrul) ? data.admrul : [data.admrul]) : [];
        for (const it of items) {
            const dateStr = it["공포일자"] || "19000101";
            if (parseInt(dateStr) >= 20200101) {
                allVersions.push({ status: "MOD", kind: "고시", title: it["행정규칙명"], date: dateStr, id: it["행정규칙ID"], diff_url: null, detected_at_utc: `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}T00:00:00Z` });
            }
        }
    } catch (e) { console.warn(`[WARN] Admrul fetch failed for ${query}: ${e.message}`); } 
    return allVersions;
}

async function fetchAllBillVersions(query, age) {
    const allVersions = [];
    const params = new URLSearchParams({ KEY: ASSEMBLY_KEY, Type: "json", pIndex: 1, pSize: 100, BILL_NM: query, AGE: age });
    try {
        const r = await fetchWithTimeout(`${ASSEMBLY_BASE}/TVBPMBILL11?${params.toString()}`);
        if(!r.ok) throw new Error(`HTTP error! status: ${r.status}`);
        const data = await r.json();
        const rows = data.TVBPMBILL11[1].row;
        for (const it of rows) {
            const dateStr = (it.PROPOSE_DT || "1900-01-01").split(' ')[0].replace(/-/g, '');
            if (parseInt(dateStr) >= 20200101) {
                allVersions.push({ status: "MOD", kind: "의안", title: it.BILL_NAME, date: it.PROPOSE_DT, id: it.BILL_ID, diff_url: null, detected_at_utc: `${it.PROPOSE_DT}T00:00:00Z` });
            }
        }
    } catch(e) { console.warn(`[WARN] Bill fetch failed for ${query}: ${e.message}`); } 
    return allVersions;
}

async function main() {
    if (!LAW_OC || !ASSEMBLY_KEY) {
        console.error("[ERROR] LAW_OC or ASSEMBLY_KEY env var is not set.");
        return;
    }
    console.log("Starting full backfill...");
    let historicalItems = [];

    for (const name of LAW_NAMES) {
        console.log(`Fetching law: ${name}...`);
        historicalItems.push(...await fetchAllLawVersions(name));
    }
    for (const query of ADMRUL_QUERIES) {
        console.log(`Fetching admrul: ${query}...`);
        historicalItems.push(...await fetchAllAdmrulVersions(query));
    }
    for (const age of ["21", "22"]) { // 21대, 22대 국회
        for (const query of BILL_KEYWORDS) {
            console.log(`Fetching bill (age ${age}): ${query}...`);
            historicalItems.push(...await fetchAllBillVersions(query, age));
        }
    }

    const mergedItems = new Map();
    for (const item of historicalItems) {
        const key = `${item.id}-${item.date}`;
        if (!mergedItems.has(key)) mergedItems.set(key, item);
    }
    
    const finalItems = Array.from(mergedItems.values()).sort((a, b) => b.detected_at_utc.localeCompare(a.detected_at_utc));
    fs.writeFileSync(CHANGELOG_PATH, JSON.stringify({ items: finalItems }, null, 2), 'utf-8');
    console.log(`
Backfill complete. Total ${finalItems.length} items saved.`);
}

main();
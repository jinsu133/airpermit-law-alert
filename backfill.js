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

async function fetchWithTimeout(url, options = {}, timeout = 60000) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);
    const response = await fetch(url, {
        ...options,
        signal: controller.signal  
    });
    clearTimeout(id);
    return response;
}

async function fetchAllLawVersions(lawName) {
    const allVersions = [];
    const params = new URLSearchParams({
        OC: LAW_OC,
        target: "law",
        type: "JSON",
        query: lawName,
        display: "100",
        sort: "ddes"
    });
    const url = `${LAW_DRF_BASE}/lawSearch.do?${params.toString()}`;
    
    try {
        const r = await fetchWithTimeout(url);
        if (!r.ok) throw new Error(`HTTP error! status: ${r.status}`);
        const data = await r.json();
        const items = data.LawSearch?.law ? (Array.isArray(data.LawSearch.law) ? data.LawSearch.law : [data.LawSearch.law]) : [];

        for (const it of items) {
            const promulgationDateStr = it["공포일자"] || "19000101";
            if (parseInt(promulgationDateStr) >= 20200101) {
                allVersions.push({
                    status: "MOD",
                    kind: "법령",
                    title: it["법령명한글"],
                    date: it["공포일자"],
                    id: it["법령ID"],
                    diff_url: null,
                    detected_at_utc: `${promulgationDateStr.slice(0, 4)}-${promulgationDateStr.slice(4, 6)}-${promulgationDateStr.slice(6, 8)}T00:00:00Z`
                });
            }
        }
    } catch (e) {
        console.warn(`[WARN] Failed to fetch all versions for ${lawName}: ${e}`);
    }
    return allVersions;
}

async function main() {
    if (!LAW_OC) {
        console.error("[ERROR] LAW_OC environment variable is not set. Cannot run backfill. e.g., LAW_OC=your_id node backfill.js");
        return;
    }

    console.log("Starting backfill process with updated law list...");
    let historicalItems = [];

    for (const name of LAW_NAMES) {
        console.log(`Fetching history for law: ${name}...`);
        const versions = await fetchAllLawVersions(name);
        historicalItems.push(...versions);
        console.log(`  > Found ${versions.length} versions since 2020.`);
    }

    let existingItems = [];
    if (fs.existsSync(CHANGELOG_PATH)) {
        try {
            const logData = JSON.parse(fs.readFileSync(CHANGELOG_PATH, 'utf-8'));
            existingItems = logData.items || [];
            console.log(`Loaded ${existingItems.length} items from existing changelog.`);
        } catch {
            console.warn("[WARN] Could not parse existing changelog.json. It will be overwritten.");
        }
    }

    const mergedItems = new Map();
    for (const item of historicalItems) {
        mergedItems.set(`${item.id}-${item.date}`, item);
    }
    for (const item of existingItems) {
        const key = `${item.id}-${item.date}`;
        if (!mergedItems.has(key)) {
            mergedItems.set(key, item);
        }
    }
    
    const finalItems = Array.from(mergedItems.values()).sort((a, b) => b.detected_at_utc.localeCompare(a.detected_at_utc));

    const newChangelog = { items: finalItems };
    fs.writeFileSync(CHANGELOG_PATH, JSON.stringify(newChangelog, null, 2), 'utf-8');

    console.log(`
Backfill complete. Total ${finalItems.length} items saved to changelog.json.`);
}

main();

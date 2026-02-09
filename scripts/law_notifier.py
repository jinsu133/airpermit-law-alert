# -*- coding: utf-8 -*-
"""
법령/고시/의안 알림 - 정적 웹용 생성기
- web 모드: public/updates.json, public/changes.json, public/health.json 생성 + data/state.json 업데이트
- 키는 환경변수(GitHub Secrets)로만 주입 (절대 코드/파일에 하드코딩 금지)
"""

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = DATA_DIR / "state.json"
HISTORY_PATH = DATA_DIR / "history.json"
CHANGELOG_PATH = BASE_DIR / "public" / "changelog.json"

KST = timezone(timedelta(hours=9))
ASSEMBLY_BASE = "https://open.assembly.go.kr/portal/openapi"

# 로컬에서만 .env 사용(레포에 커밋 금지)
if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env")

LAW_OC = os.getenv("LAW_OC", "").strip()
ASSEMBLY_KEY = os.getenv("ASSEMBLY_KEY", "").strip()
ASSEMBLY_AGE = os.getenv("ASSEMBLY_AGE", "").strip()
HISTORY_START_DATE_RAW = os.getenv("CHANGELOG_START_DATE", "20210101").strip()

LAW_DRF_BASES_ENV = os.getenv("LAW_DRF_BASES", "").strip()
LAW_DRF_BASE = os.getenv("LAW_DRF_BASE", "").strip()


def unique_keep_order(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for v in values:
        x = (v or "").strip().rstrip("/")
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


_law_base_candidates: List[str] = []
if LAW_DRF_BASES_ENV:
    _law_base_candidates.extend([x.strip() for x in LAW_DRF_BASES_ENV.split(",") if x.strip()])
if LAW_DRF_BASE:
    _law_base_candidates.append(LAW_DRF_BASE)

# 운영 기본값: 공공 API 직결 + 프록시(장애 대비)
_law_base_candidates.extend(
    [
        "https://www.law.go.kr/DRF",
        "https://law-proxy.jinsu133.workers.dev/DRF",
    ]
)
LAW_DRF_BASES = unique_keep_order(_law_base_candidates)

LAW_NAMES = [
    "대기환경보전법",
    "대기환경보전법 시행령",
    "대기환경보전법 시행규칙",
    "환경분야 시험·검사 등에 관한 법률",
    "환경분야 시험 검사 등에 관한 법률",
    "환경분야 시험·검사 등에 관한 법률 시행령",
    "환경분야 시험·검사 등에 관한 법률 시행규칙",
    "대기관리권역의 대기환경개선에 관한 특별법",
    "대기관리권역의 대기환경개선에 관한 특별법 시행령",
    "대기관리권역의 대기환경개선에 관한 특별법 시행규칙",
    "환경오염시설의 통합관리에 관한 법률",
    "환경오염시설의 통합관리에 관한 법률 시행령",
    "환경오염시설의 통합관리에 관한 법률 시행규칙",
]

ADMRUL_QUERIES = [
    "환경시험·검사기관 정도관리 운영등에 관한 규정",
    "환경시험 검사기관 정도관리 운영",
    "대기오염공정시험기준",
    "대기배출시설",
    "대기오염물질",
    "방지시설",
    "배출가스",
    "자가측정",
    "기본부과금",
    "초과부과금",
    "통합허가",
    "통합관리",
    "굴뚝",
    "미세먼지",
    "오존",
]

# 국회 의안 모니터링: 법령알림 화면에서 보여줄 핵심 범위
BILL_LAW_KEYWORDS = [
    "대기환경보전법",
    "환경분야 시험·검사 등에 관한 법률",
    "대기관리권역의 대기환경개선에 관한 특별법",
    "환경오염시설의 통합관리에 관한 법률",
]
BILL_STRICT_KEYWORDS = [
    "대기환경",
    "대기오염",
    "대기관리권역",
    "배출시설",
    "방지시설",
    "배출가스",
    "자가측정",
    "굴뚝",
    "미세먼지",
    "오염물질",
    "환경오염시설",
    "공정시험기준",
    "환경시험",
    "시험·검사",
]
BILL_EXTRA_KEYWORDS = [x.strip() for x in os.getenv("BILL_EXTRA_KEYWORDS", "").split(",") if x.strip()]
BILL_HISTORY_AGES = [x.strip() for x in os.getenv("BILL_HISTORY_AGES", "21,22").split(",") if x.strip()]

SERVICE_SEARCH_BILL = os.getenv("SERVICE_SEARCH_BILL", "TVBPMBILL11").strip() or "TVBPMBILL11"
BILL_SERVICES_RECENT = [
    {"service": "nzmimeepazxkubdpn", "label": "국회의원 발의법률안", "params": {"pSize": 100}},
    {"service": "nxjuyqnxadtotdrbw", "label": "최근 본회의 처리 의안", "params": {"pSize": 100}},
    {"service": "nxtkyptyaolzcbfwl", "label": "위원회안·대안", "params": {"pSize": 100}},
    {"service": "nwbpacrgavhjryiph", "label": "본회의 처리안건_법률안", "params": {"pSize": 100}},
]

STATUS_KO = {
    "NEW": "신규",
    "MOD": "변경",
    "OK": "유지",
}

LAW_CHANGE_FIELDS: List[Tuple[str, str]] = [
    ("공포일자", "ld"),
    ("공포번호", "ln"),
    ("제개정구분", "reform_type"),
]
ADMRUL_CHANGE_FIELDS: List[Tuple[str, str]] = [
    ("발령일자", "promulgation_date"),
    ("시행일자", "enforce_date"),
    ("발령번호", "num"),
]
BILL_CHANGE_FIELDS: List[Tuple[str, str]] = [
    ("의안번호", "bill_no"),
    ("처리결과", "proc_result"),
    ("제안일", "propose_dt"),
]


def now_kst_iso_ms() -> str:
    return datetime.now(KST).isoformat(timespec="milliseconds")


def now_utc_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def current_assembly_age() -> str:
    """
    국회 회기(대수) 자동 계산.
    - 21대: 2020-05-30 시작
    - 22대: 2024-05-30 시작
    - 이후 4년 주기
    """
    today = datetime.now(KST).date()
    base_age = 21
    base_start = date(2020, 5, 30)
    if today < base_start:
        return str(base_age)
    years = today.year - base_start.year
    if (today.month, today.day) < (base_start.month, base_start.day):
        years -= 1
    term = years // 4
    return str(base_age + max(0, term))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"laws": {}, "admruls": {}, "bills": {}, "last_run": None}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"laws": {}, "admruls": {}, "bills": {}, "last_run": None}
    data.setdefault("laws", {})
    data.setdefault("admruls", {})
    data.setdefault("bills", {})
    return data


def save_state(st: Dict[str, Any]) -> None:
    ensure_parent(STATE_PATH)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def load_history() -> Dict[str, Any]:
    default = {"seeded_from": None, "items": []}
    src_text = ""
    if HISTORY_PATH.exists():
        src_text = HISTORY_PATH.read_text(encoding="utf-8")
    elif CHANGELOG_PATH.exists():
        # 기존 changelog.json 포맷(items 배열) 호환
        src_text = CHANGELOG_PATH.read_text(encoding="utf-8")
    if not src_text:
        return default
    try:
        data = json.loads(src_text)
    except Exception:
        return default
    if isinstance(data, list):
        return {"seeded_from": None, "items": data}
    if not isinstance(data, dict):
        return default
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    return {
        "seeded_from": data.get("seeded_from"),
        "items": items,
    }


def save_history(history: Dict[str, Any]) -> None:
    ensure_parent(HISTORY_PATH)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def history_entry_from_item(item: Dict[str, Any], source: str, fallback_iso: str) -> Dict[str, Any]:
    entry = {
        "status": str(item.get("status", "MOD")),
        "status_ko": str(item.get("status_ko", STATUS_KO.get(str(item.get("status", "MOD")), "변경"))),
        "kind": str(item.get("kind", "")),
        "title": str(item.get("title", "")),
        "date": normalize_date(item.get("date", "")),
        "id": str(item.get("id", "")),
        "diff_url": item.get("diff_url"),
        "change_summary": str(item.get("change_summary", "") or ""),
        "source": source,
        "detected_at_utc": normalize_detected_at_utc(item, fallback_iso),
    }
    entry["history_key"] = history_item_key(entry)
    return entry


def merge_history_items(
    existing_items: List[Dict[str, Any]],
    incoming_items: List[Dict[str, Any]],
    cutoff_yyyymmdd: str,
) -> List[Dict[str, Any]]:
    cutoff = safe_int_yyyymmdd(cutoff_yyyymmdd)
    merged: Dict[str, Dict[str, Any]] = {}

    for raw in (existing_items + incoming_items):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["date"] = normalize_date(item.get("date", ""))
        item["detected_at_utc"] = normalize_detected_at_utc(item, now_utc_iso_ms())
        if not item.get("history_key"):
            item["history_key"] = history_item_key(item)
        if not item.get("status_ko"):
            item["status_ko"] = STATUS_KO.get(str(item.get("status", "MOD")), "변경")

        date_num = safe_int_yyyymmdd(item.get("date", "")) or safe_int_yyyymmdd(yyyymmdd_from_iso(item["detected_at_utc"]))
        if date_num and date_num < cutoff:
            continue

        key = str(item.get("history_key", "")).strip() or history_item_key(item)
        prev = merged.get(key)
        if not prev:
            merged[key] = item
            continue

        # 같은 항목이면 최신 detected_at_utc 기준으로 갱신
        if iso_sort_value(item.get("detected_at_utc", "")) >= iso_sort_value(prev.get("detected_at_utc", "")):
            merged[key] = item

    out = list(merged.values())
    out.sort(
        key=lambda item: (
            -iso_sort_value(item.get("detected_at_utc", "")),
            -date_sort_value(item.get("date", "")),
            str(item.get("kind", "")),
            str(item.get("title", "")),
        )
    )
    return out


def collect_law_backfill_items(cutoff_yyyymmdd: str) -> List[Dict[str, Any]]:
    cutoff = safe_int_yyyymmdd(cutoff_yyyymmdd)
    out: List[Dict[str, Any]] = []

    for law_name in LAW_NAMES:
        params = {
            "OC": LAW_OC,
            "target": "law",
            "type": "JSON",
            "query": law_name,
            "display": "100",
            "sort": "ddes",
        }
        data = law_api_request("lawSearch.do", params, f"law_backfill:{law_name}")
        if not data:
            continue
        raw = ((data.get("LawSearch") or {}).get("law")) or []
        items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        for item in items:
            ld = normalize_date(item.get("공포일자", ""))
            if not ld or safe_int_yyyymmdd(ld) < cutoff:
                continue
            title = str(item.get("법령명한글") or law_name)
            info = {
                "ld": ld,
                "ln": str(item.get("공포번호", "") or ""),
                "reform_type": str(item.get("제개정구분명", "") or ""),
                "law_id": str(item.get("법령일련번호") or item.get("법령ID") or ""),
            }
            item_id = f"{info['ln']}|{info['ld']}|{info['reform_type']}".strip("|") or title
            out.append(
                {
                    "status": "MOD",
                    "status_ko": STATUS_KO["MOD"],
                    "kind": "법령",
                    "title": title,
                    "date": ld,
                    "id": item_id,
                    "diff_url": build_law_diff_url(title, info),
                    "change_summary": "기준일(2021-01-01) 이후 누적 백필",
                    "detected_at_utc": to_iso_utc_from_yyyymmdd(ld),
                }
            )
    return out


def collect_admrul_backfill_items(cutoff_yyyymmdd: str) -> List[Dict[str, Any]]:
    cutoff = safe_int_yyyymmdd(cutoff_yyyymmdd)
    out: List[Dict[str, Any]] = []

    for keyword in ADMRUL_QUERIES:
        params = {
            "OC": LAW_OC,
            "target": "admrul",
            "type": "JSON",
            "query": keyword,
            "display": "100",
            "sort": "ddes",
        }
        data = law_api_request("lawSearch.do", params, f"admrul_backfill:{keyword}")
        if not data:
            continue
        container = data.get("AdmRulSearch") or data.get("AdmrulSearch") or data.get("admRulSearch") or {}
        raw = container.get("admrul", [])
        items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        for item in items:
            title = str(item.get("행정규칙명", "") or "")
            dept = str(item.get("소관부처명", "") or "")
            if dept and not any(x in dept for x in ("환경부", "국립환경과학원", "기후에너지환경부")):
                continue

            date_text = normalize_date(item.get("발령일자") or item.get("공포일자") or "")
            if not date_text or safe_int_yyyymmdd(date_text) < cutoff:
                continue

            info = {
                "num": str(item.get("발령번호") or item.get("고시번호") or item.get("행정규칙ID") or ""),
                "promulgation_date": date_text,
                "enforce_date": normalize_date(item.get("시행일자") or ""),
                "admrul_id": str(item.get("행정규칙일련번호") or item.get("행정규칙ID") or ""),
            }
            item_id = f"{info['num']}|{info['promulgation_date']}|{info['enforce_date']}".strip("|") or title
            out.append(
                {
                    "status": "MOD",
                    "status_ko": STATUS_KO["MOD"],
                    "kind": "고시",
                    "title": title,
                    "date": info["promulgation_date"],
                    "id": item_id,
                    "diff_url": build_admrul_diff_url(title, info),
                    "change_summary": "기준일(2021-01-01) 이후 누적 백필",
                    "detected_at_utc": to_iso_utc_from_yyyymmdd(info["promulgation_date"]),
                }
            )
    return out


def collect_bill_backfill_items(cutoff_yyyymmdd: str) -> List[Dict[str, Any]]:
    cutoff = safe_int_yyyymmdd(cutoff_yyyymmdd)
    out: List[Dict[str, Any]] = []
    seen = set()

    for age in BILL_HISTORY_AGES:
        for keyword in BILL_LAW_KEYWORDS:
            try:
                data = assembly_call(SERVICE_SEARCH_BILL, {"BILL_NM": keyword, "pSize": 100, "AGE": age})
            except Exception as exc:
                print(f"[WARN] bill_backfill 실패: age={age} keyword={keyword} -> {exc}")
                continue
            for row in extract_rows(data):
                bill_id = str(row.get("BILL_ID") or row.get("billId") or "").strip()
                if not bill_id:
                    continue
                title = str(row.get("BILL_NAME") or row.get("TITLE") or "")
                if not is_target_bill_title(title):
                    continue
                propose = normalize_date(row.get("PROPOSE_DT") or row.get("RST_PROPOSE_DT") or "")
                if not propose or safe_int_yyyymmdd(propose) < cutoff:
                    continue
                dedupe_key = f"{bill_id}|{propose}"
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                out.append(
                    {
                        "status": "MOD",
                        "status_ko": STATUS_KO["MOD"],
                        "kind": "의안",
                        "title": title,
                        "date": propose,
                        "id": bill_id,
                        "diff_url": build_bill_diff_url(bill_id),
                        "change_summary": "기준일(2021-01-01) 이후 누적 백필",
                        "detected_at_utc": to_iso_utc_from_yyyymmdd(propose),
                    }
                )
    return out


def seed_history_items(cutoff_yyyymmdd: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    items.extend(collect_law_backfill_items(cutoff_yyyymmdd))
    items.extend(collect_admrul_backfill_items(cutoff_yyyymmdd))
    items.extend(collect_bill_backfill_items(cutoff_yyyymmdd))
    return items


def require_keys() -> None:
    if not LAW_OC:
        raise RuntimeError("LAW_OC missing (GitHub Secrets에 설정 필요)")
    if not ASSEMBLY_KEY:
        raise RuntimeError("ASSEMBLY_KEY missing (GitHub Secrets에 설정 필요)")


def normalize_name(text: str) -> str:
    x = str(text or "").replace(" ", "").replace("\t", "")
    return x.replace("ㆍ", "·")


def normalize_date(text: str) -> str:
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return digits[:8]


def date_sort_value(text: str) -> int:
    digits = normalize_date(text)
    return int(digits) if digits else 0


def history_start_yyyymmdd() -> str:
    d = normalize_date(HISTORY_START_DATE_RAW)
    return d if d else "20210101"


def safe_int_yyyymmdd(text: str) -> int:
    digits = normalize_date(text)
    return int(digits) if digits else 0


def to_iso_utc_from_yyyymmdd(yyyymmdd: str) -> str:
    digits = normalize_date(yyyymmdd)
    if len(digits) != 8:
        return now_utc_iso_ms()
    return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}T00:00:00Z"


def yyyymmdd_from_iso(iso: str) -> str:
    if not iso:
        return ""
    digits = normalize_date(iso)
    return digits[:8]


def normalize_detected_at_utc(item: Dict[str, Any], fallback_iso: str) -> str:
    iso = str(item.get("detected_at_utc") or "").strip()
    if iso:
        return iso
    date_text = normalize_date(item.get("date", ""))
    if date_text:
        return to_iso_utc_from_yyyymmdd(date_text)
    return fallback_iso


def history_item_key(item: Dict[str, Any]) -> str:
    return "||".join(
        [
            str(item.get("kind", "")).strip(),
            str(item.get("id", "")).strip(),
            normalize_date(item.get("date", "")),
            str(item.get("title", "")).strip(),
        ]
    )


def iso_sort_value(iso: str) -> float:
    s = str(iso or "").strip()
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def count_by_kind(items: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"법령": 0, "고시": 0, "의안": 0}
    for item in items:
        kind = str(item.get("kind", ""))
        if kind in out:
            out[kind] += 1
    return out


def law_api_request(endpoint: str, params: Dict[str, Any], label: str) -> Optional[Dict[str, Any]]:
    headers = {"User-Agent": "law-alert/1.0"}
    errors: List[str] = []

    for base in LAW_DRF_BASES:
        url = f"{base}/{endpoint.lstrip('/')}"
        try:
            resp = requests.get(url, params=params, timeout=25, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            errors.append(f"{url} -> {exc}")
        except ValueError as exc:
            errors.append(f"{url} -> JSON parse error: {exc}")

    print(f"[WARN] law_api_request 실패: {label}")
    for msg in errors:
        print(f"  - {msg}")
    return None


def law_search(law_name: str) -> Optional[Dict[str, Any]]:
    params = {
        "OC": LAW_OC,
        "target": "law",
        "type": "JSON",
        "query": law_name,
        "display": "30",
        "sort": "ddes",
    }
    data = law_api_request("lawSearch.do", params, f"law_search:{law_name}")
    if not data:
        return None

    container = data.get("LawSearch", {})
    raw = container.get("law", [])
    items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    if not items:
        return None

    first = items[0]
    return {
        "law_name": first.get("법령명한글", law_name),
        "ld": normalize_date(first.get("공포일자", "")),
        "ln": str(first.get("공포번호", "") or ""),
        "reform_type": str(first.get("제개정구분명", "") or ""),
        "law_id": str(first.get("법령일련번호") or first.get("법령ID") or ""),
    }


def admrul_search(keyword: str) -> List[Dict[str, Any]]:
    # 고시는 lawSearch.do + target=admrul 로 조회해야 안정적으로 응답됨.
    params = {
        "OC": LAW_OC,
        "target": "admrul",
        "type": "JSON",
        "query": keyword,
        "display": "20",
        "sort": "ddes",
    }
    data = law_api_request("lawSearch.do", params, f"admrul_search:{keyword}")
    if not data:
        return []

    container = data.get("AdmRulSearch") or data.get("AdmrulSearch") or data.get("admRulSearch") or {}
    raw = container.get("admrul", [])
    items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])

    out: List[Dict[str, Any]] = []
    for item in items:
        title = str(item.get("행정규칙명", "") or "")
        dept = str(item.get("소관부처명", "") or "")

        # 환경부/국립환경과학원 계열만 표시
        if dept and not any(x in dept for x in ("환경부", "국립환경과학원", "기후에너지환경부")):
            continue

        out.append(
            {
                "title": title,
                "dept": dept,
                "num": str(item.get("발령번호") or item.get("고시번호") or item.get("행정규칙ID") or ""),
                "promulgation_date": normalize_date(item.get("발령일자") or item.get("공포일자") or ""),
                "enforce_date": normalize_date(item.get("시행일자") or ""),
                "admrul_id": str(item.get("행정규칙일련번호") or item.get("행정규칙ID") or ""),
            }
        )

    # 중복 제거(행정규칙명+번호)
    uniq: List[Dict[str, Any]] = []
    seen = set()
    for item in out:
        key = f"{item.get('title', '')}::{item.get('num', '')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def assembly_call(service: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = {"KEY": ASSEMBLY_KEY, "Type": "json", "pIndex": 1}
    query.update(params)
    resp = requests.get(f"{ASSEMBLY_BASE}/{service}", params=query, timeout=25)
    resp.raise_for_status()
    return resp.json()


def extract_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    for value in data.values():
        if not isinstance(value, list):
            continue
        for elem in value:
            if isinstance(elem, dict) and "row" in elem:
                rows = elem["row"]
                if isinstance(rows, list):
                    return rows
                if isinstance(rows, dict):
                    return [rows]
    return []


def is_target_bill_title(title: str) -> bool:
    t = str(title or "").strip()
    if not t:
        return False
    if any(keyword in t for keyword in BILL_LAW_KEYWORDS):
        return True
    strict = BILL_STRICT_KEYWORDS + BILL_EXTRA_KEYWORDS
    return any(keyword in t for keyword in strict)


def bill_items() -> List[Dict[str, Any]]:
    age = ASSEMBLY_AGE or "auto"
    if age.lower() == "auto":
        age = current_assembly_age()

    out: List[Dict[str, Any]] = []
    seen_ids = set()

    # Strategy 1: 핵심 법률명 직접 검색
    for keyword in BILL_LAW_KEYWORDS:
        try:
            data = assembly_call(SERVICE_SEARCH_BILL, {"BILL_NM": keyword, "pSize": 50, "AGE": age})
        except Exception as exc:
            print(f"[WARN] bill_search 실패: {keyword} -> {exc}")
            continue

        for row in extract_rows(data):
            bill_id = row.get("BILL_ID") or row.get("billId")
            if not bill_id or bill_id in seen_ids:
                continue

            title = str(row.get("BILL_NAME") or row.get("TITLE") or "")
            if not is_target_bill_title(title):
                continue

            out.append(
                {
                    "bill_id": str(bill_id),
                    "bill_no": str(row.get("BILL_NO") or row.get("BILLNO") or ""),
                    "bill_name": title,
                    "propose_dt": normalize_date(row.get("PROPOSE_DT") or row.get("RST_PROPOSE_DT") or ""),
                    "proc_result": str(row.get("PROC_RESULT") or row.get("PROC_RESULT_CD") or ""),
                }
            )
            seen_ids.add(str(bill_id))

    # Strategy 2: 최근 의안 목록 조회 + 엄격 필터
    for svc_info in BILL_SERVICES_RECENT:
        svc_code = svc_info["service"]
        params = dict(svc_info["params"])
        if "AGE" in params:
            params["AGE"] = age

        try:
            data = assembly_call(svc_code, params)
        except Exception as exc:
            print(f"[WARN] bill_recent 실패: {svc_info['label']} -> {exc}")
            continue

        for row in extract_rows(data):
            bill_id = row.get("BILL_ID") or row.get("billId")
            if not bill_id or str(bill_id) in seen_ids:
                continue

            title = str(row.get("BILL_NAME") or row.get("TITLE") or row.get("billName") or "")
            if not is_target_bill_title(title):
                continue

            out.append(
                {
                    "bill_id": str(bill_id),
                    "bill_no": str(row.get("BILL_NO") or row.get("billNo") or ""),
                    "bill_name": title,
                    "propose_dt": normalize_date(row.get("PROPOSE_DT") or row.get("proposeDt") or ""),
                    "proc_result": str(row.get("PROC_RESULT") or row.get("PROC_RESULT_CD") or ""),
                }
            )
            seen_ids.add(str(bill_id))

    out.sort(key=lambda item: date_sort_value(item.get("propose_dt", "")), reverse=True)
    return out[:120]


def status_from_prev(prev: Optional[Dict[str, Any]], status_key: str) -> str:
    if not prev:
        return "NEW"
    return "MOD" if prev.get("status_key") != status_key else "OK"


def write_json(path: Path, obj: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def build_change_summary(
    prev: Optional[Dict[str, Any]], current: Dict[str, Any], fields: List[Tuple[str, str]]
) -> str:
    if not prev:
        return "신규 감지"

    diffs: List[str] = []
    for label, key in fields:
        old_val = str(prev.get(key, "") or "").strip()
        new_val = str(current.get(key, "") or "").strip()
        if old_val != new_val:
            diffs.append(f"{label}: {old_val or '-'} -> {new_val or '-'}")
    return "; ".join(diffs) if diffs else "변경 없음"


def build_law_diff_url(title: str, info: Dict[str, Any]) -> str:
    law_id = str(info.get("law_id") or "").strip()
    if law_id:
        return f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={law_id}&efYd={info.get('ld', '')}"
    return f"https://www.law.go.kr/LSW/lsSc.do?menuId=1&query={title}"


def build_admrul_diff_url(title: str, info: Dict[str, Any]) -> str:
    admrul_id = str(info.get("admrul_id") or "").strip()
    if admrul_id:
        return f"https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq={admrul_id}"
    return f"https://www.law.go.kr/LSW/lsSc.do?menuId=1&query={title}"


def build_bill_diff_url(bill_id: str) -> str:
    return f"https://likms.assembly.go.kr/bill/billDetail.do?billId={bill_id}"


def dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rank = {"NEW": 3, "MOD": 2, "OK": 1}
    merged: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = f"{item.get('kind', '')}::{item.get('title', '')}::{item.get('id', '')}"
        prev = merged.get(key)
        if not prev:
            merged[key] = item
            continue
        if rank.get(str(item.get("status", "")), 0) > rank.get(str(prev.get("status", "")), 0):
            merged[key] = item
    return list(merged.values())


def sort_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kind_order = {"법령": 0, "고시": 1, "의안": 2}
    return sorted(
        items,
        key=lambda item: (
            kind_order.get(str(item.get("kind", "")), 9),
            -date_sort_value(str(item.get("date", ""))),
            str(item.get("title", "")),
        ),
    )


def fallback_law_items(state_laws: Dict[str, Any], existed_titles: set) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, prev in state_laws.items():
        title = str(prev.get("law_name") or prev.get("name") or key or "")
        if not title or title in existed_titles:
            continue
        if not any(normalize_name(title).startswith(normalize_name(seed)) for seed in LAW_NAMES):
            continue

        info = {
            "ld": normalize_date(prev.get("ld") or prev.get("date") or ""),
            "ln": str(prev.get("ln") or prev.get("num") or ""),
            "reform_type": str(prev.get("reform_type") or prev.get("type") or ""),
            "law_id": str(prev.get("law_id") or prev.get("id") or ""),
        }
        item_id = f"{info['ln']}|{info['ld']}|{info['reform_type']}".strip("|") or title
        out.append(
            {
                "status": "OK",
                "status_ko": STATUS_KO["OK"],
                "kind": "법령",
                "title": title,
                "date": info["ld"],
                "id": item_id,
                "diff_url": build_law_diff_url(title, info),
                "note": "법령 API 응답 누락으로 이전 성공 데이터를 표시합니다.",
            }
        )
    return out


def fallback_admrul_items(state_admruls: Dict[str, Any], existed_keys: set) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, prev in state_admruls.items():
        title = str(prev.get("title") or "")
        num = str(prev.get("num") or "")
        uniq_key = f"{title}::{num}"
        if not title or uniq_key in existed_keys:
            continue

        info = {
            "promulgation_date": normalize_date(prev.get("promulgation_date") or ""),
            "enforce_date": normalize_date(prev.get("enforce_date") or ""),
            "num": num,
            "admrul_id": str(prev.get("admrul_id") or ""),
        }
        item_id = f"{info['num']}|{info['promulgation_date']}|{info['enforce_date']}".strip("|") or uniq_key
        out.append(
            {
                "status": "OK",
                "status_ko": STATUS_KO["OK"],
                "kind": "고시",
                "title": title,
                "date": info["promulgation_date"] or info["enforce_date"],
                "id": item_id,
                "diff_url": build_admrul_diff_url(title, info),
                "note": "고시 API 응답 누락으로 이전 성공 데이터를 표시합니다.",
            }
        )
    return out


def run_web(out_dir: str) -> None:
    require_keys()
    state = load_state()
    all_items: List[Dict[str, Any]] = []
    generated_kst = now_kst_iso_ms()
    generated_utc = now_utc_iso_ms()
    used_fallback = {"laws": False, "admruls": False}

    # laws
    seen_law_titles = set()
    for law_name in LAW_NAMES:
        info = law_search(law_name)
        if not info:
            continue

        key = str(info.get("law_name") or law_name)
        current_key = "|".join([info.get("ld", ""), info.get("ln", ""), info.get("reform_type", "")])
        prev = state["laws"].get(key)
        status = status_from_prev(prev, current_key)
        item_id = f"{info.get('ln', '')}|{info.get('ld', '')}|{info.get('reform_type', '')}".strip("|") or key

        item = {
            "status": status,
            "status_ko": STATUS_KO.get(status, status),
            "kind": "법령",
            "title": key,
            "date": info.get("ld", ""),
            "id": item_id,
            "diff_url": build_law_diff_url(key, info),
        }
        if status in ("NEW", "MOD"):
            item["change_summary"] = build_change_summary(prev, info, LAW_CHANGE_FIELDS)
        all_items.append(item)
        seen_law_titles.add(key)
        state["laws"][key] = {"status_key": current_key, **info}

    if not seen_law_titles and state.get("laws"):
        all_items.extend(fallback_law_items(state["laws"], seen_law_titles))
        used_fallback["laws"] = True

    # admruls
    seen_admrul_keys = set()
    for keyword in ADMRUL_QUERIES:
        for info in admrul_search(keyword):
            key = f"{info.get('title', '')}::{info.get('num', '')}"
            if key in seen_admrul_keys:
                continue
            seen_admrul_keys.add(key)

            current_key = "|".join([info.get("promulgation_date", ""), info.get("enforce_date", ""), info.get("num", "")])
            prev = state["admruls"].get(key)
            status = status_from_prev(prev, current_key)
            item_id = f"{info.get('num', '')}|{info.get('promulgation_date', '')}|{info.get('enforce_date', '')}".strip("|") or key

            item = {
                "status": status,
                "status_ko": STATUS_KO.get(status, status),
                "kind": "고시",
                "title": info.get("title", ""),
                "date": info.get("promulgation_date") or info.get("enforce_date") or "",
                "id": item_id,
                "diff_url": build_admrul_diff_url(info.get("title", ""), info),
            }
            if status in ("NEW", "MOD"):
                item["change_summary"] = build_change_summary(prev, info, ADMRUL_CHANGE_FIELDS)
            all_items.append(item)
            state["admruls"][key] = {"status_key": current_key, **info}

    if not seen_admrul_keys and state.get("admruls"):
        all_items.extend(fallback_admrul_items(state["admruls"], seen_admrul_keys))
        used_fallback["admruls"] = True

    # bills
    for info in bill_items():
        bill_id = str(info["bill_id"])
        current_key = f"{info.get('bill_no', '')}|{info.get('proc_result', '')}|{info.get('propose_dt', '')}"
        prev = state["bills"].get(bill_id)
        status = "NEW" if not prev else ("MOD" if prev.get("status_key") != current_key else "OK")

        item = {
            "status": status,
            "status_ko": STATUS_KO.get(status, status),
            "kind": "의안",
            "title": info.get("bill_name", ""),
            "date": info.get("propose_dt", ""),
            "id": bill_id,
            "diff_url": build_bill_diff_url(bill_id),
            "detected_at_utc": generated_utc,
        }
        if status in ("NEW", "MOD"):
            item["change_summary"] = build_change_summary(prev, info, BILL_CHANGE_FIELDS)
        all_items.append(item)
        state["bills"][bill_id] = {"status_key": current_key, **info}

    all_items = sort_items(dedupe_items(all_items))
    delta_change_items = [item for item in all_items if str(item.get("status", "")).upper() in ("NEW", "MOD")]
    kind_count = count_by_kind(all_items)

    cutoff_yyyymmdd = history_start_yyyymmdd()
    history = load_history()
    existing_history_items = history.get("items", [])
    history_seeded_from = normalize_date(history.get("seeded_from") or "")
    seeded_now = False

    needs_seed = (not existing_history_items) or (safe_int_yyyymmdd(history_seeded_from) < safe_int_yyyymmdd(cutoff_yyyymmdd))
    if needs_seed:
        print(f"[INFO] history seed 시작: {cutoff_yyyymmdd} 이후 변경분 누적")
        seed_items = seed_history_items(cutoff_yyyymmdd)
        seed_entries = [history_entry_from_item(item, source="backfill", fallback_iso=generated_utc) for item in seed_items]
        base_items = existing_history_items if history_seeded_from else []
        existing_history_items = merge_history_items(base_items, seed_entries, cutoff_yyyymmdd)
        history["seeded_from"] = cutoff_yyyymmdd
        seeded_now = True

    delta_entries = [
        history_entry_from_item(item, source="delta", fallback_iso=generated_utc) for item in delta_change_items
    ]
    cumulative_history_items = merge_history_items(existing_history_items, delta_entries, cutoff_yyyymmdd)
    history["seeded_from"] = history.get("seeded_from") or cutoff_yyyymmdd
    history["last_generated_at_utc"] = generated_utc
    history["items"] = cumulative_history_items
    save_history(history)

    history_kind_count = count_by_kind(cumulative_history_items)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_kst": generated_kst,
        "generated_at_utc": generated_utc,
        "stats": {
            "count_by_kind": kind_count,
            "fallback": used_fallback,
            "delta_count_this_run": len(delta_change_items),
            "cumulative_history_total": len(cumulative_history_items),
            "history_start_yyyymmdd": cutoff_yyyymmdd,
        },
        "items": all_items,
    }
    changes_payload = {
        "generated_at_kst": generated_kst,
        "generated_at_utc": generated_utc,
        "range_start_yyyymmdd": cutoff_yyyymmdd,
        "stats": {
            "count_by_kind": history_kind_count,
            "delta_count_this_run": len(delta_change_items),
            "total_cumulative": len(cumulative_history_items),
            "seeded_now": seeded_now,
        },
        "items": cumulative_history_items,
    }
    write_json(out_path / "updates.json", payload)
    write_json(out_path / "changes.json", changes_payload)
    write_json(out_path / "changelog.json", changes_payload)
    write_json(out_path / "health.json", {"last_success_kst": generated_kst, "last_success_utc": generated_utc})

    state["last_run"] = generated_kst
    save_state(state)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["web"], default="web")
    ap.add_argument("--out", default="public")
    args = ap.parse_args()
    run_web(args.out)


if __name__ == "__main__":
    main()

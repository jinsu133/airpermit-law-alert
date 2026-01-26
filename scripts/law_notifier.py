# -*- coding: utf-8 -*-
import argparse
import json
import os
import re
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from typing import Any, Dict, List, Optional
import difflib
import requests
from dotenv import load_dotenv

# --- 기본 설정 및 상수 ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PUBLIC_DIR = BASE_DIR / "public"
DIFF_DIR = PUBLIC_DIR / "diffs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
DIFF_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = DATA_DIR / "state.json"

KST = timezone(timedelta(hours=9))
LAW_DRF_BASE = "http://www.law.go.kr/DRF"
ASSEMBLY_BASE = "https://open.assembly.go.kr/portal/openapi"

if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env")

LAW_OC = os.getenv("LAW_OC", "").strip()
ASSEMBLY_KEY = os.getenv("ASSEMBLY_KEY", "").strip()
ASSEMBLY_AGE = os.getenv("ASSEMBLY_AGE", "").strip()

# --- 검색 대상 키워드 ---
LAW_NAMES = [
  "대기환경보전법","대기환경보전법 시행령","대기환경보전법 시행규칙",
  "환경분야 시험·검사 등에 관한 법률","환경분야 시험·검사 등에 관한 법률 시행령","환경분야 시험·검사 등에 관한 법률 시행규칙",
  "대기관리권역의 대기환경개선에 관한 특별법","대기관리권역의 대기환경개선에 관한 특별법 시행령","대기관리권역의 대기환경개선에 관한 특별법 시행규칙",
  "환경오염시설의 통합관리에 관한 법률","환경오염시설의 통합관리에 관한 법률 시행령","환경오염시설의 통합관리에 관한 법률 시행규칙",
]
ADMRUL_QUERIES = ["대기오염공정시험기준"]
BILL_KEYWORDS = ["대기환경보전법", "환경분야 시험·검사 등에 관한 법률", "대기관리권역의 대기환경개선에 관한 특별법", "환경오염시설의 통합관리에 관한 법률"]
ENV_BILL_KEYWORDS = ["대기","환경","오염","배출","온실가스","탄소","기후","미세먼지"]

# --- 유틸리티 함수 ---
def is_env_bill(name: str) -> bool:
    n = (name or "").lower()
    return any(kw.lower() in n for kw in ENV_BILL_KEYWORDS)

def now_utc_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists(): return {"laws":{}, "admruls":{}, "bills":{}}
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception: return {"laws":{}, "admruls":{}, "bills":{}}

def save_state(st: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def require_keys() -> None:
    if not LAW_OC: raise RuntimeError("LAW_OC missing")
    if not ASSEMBLY_KEY: raise RuntimeError("ASSEMBLY_KEY missing")

def make_diff_html(old_text: str, new_text: str, from_title: str, to_title: str) -> str:
    return difflib.HtmlDiff(tabsize=4, wrapcolumn=80).make_file(old_text.splitlines(), new_text.splitlines(), from_title, to_title, context=True, numlines=5)

# --- API 호출 함수 ---
def law_search(law_name: str) -> List[Dict[str, Any]]:
    params = {"OC": LAW_OC, "target": "law", "type": "JSON", "query": law_name, "display": "5"}
    try:
        r = requests.get(f"{LAW_DRF_BASE}/lawSearch.do", params=params, timeout=60) # timeout=60 적용
        r.raise_for_status()
        data = r.json()
        items = data.get("LawSearch", {}).get("law", [])
        return items if isinstance(items, list) else ([items] if items else [])
    except Exception as e:
        print(f"[WARN] law_search failed for {law_name}: {e}")
        return []

def get_law_body(law_id: str, target: str = "lsStmd") -> str:
    if not law_id: return ""
    params = {"OC": LAW_OC, "target": target, "type": "XML", "ID": law_id}
    try:
        r = requests.get(f"{LAW_DRF_BASE}/lawService.do", params=params, timeout=60) # timeout=60 적용
        r.raise_for_status()
        content_tag = "법령내용" if target == "lsStmd" else "행정규칙내용"
        match = re.search(f'<{content_tag}>(.*?)</{content_tag}>', r.text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except Exception as e:
        print(f"[WARN] get_law_body failed for ID {law_id}: {e}")
        return ""

def admrul_search(keyword: str) -> List[Dict[str, Any]]:
    params = {"OC": LAW_OC, "target": "admrul", "type": "JSON", "query": keyword, "display": "5"}
    try:
        r = requests.get(f"{LAW_DRF_BASE}/lawService.do", params=params, timeout=60) # timeout=60 적용
        r.raise_for_status()
        data = r.json()
        items = data.get("admrul", [])
        return items if isinstance(items, list) else ([items] if items else [])
    except Exception as e:
        print(f"[WARN] admrul_search failed for {keyword}: {e}")
        return []
        
def assembly_call(service: str, params: Dict[str, Any]) -> Dict[str, Any]:
    q = {"KEY": ASSEMBLY_KEY, "Type":"json", "pIndex":1}
    q.update(params)
    r = requests.get(f"{ASSEMBLY_BASE}/{service}", params=q, timeout=60) # timeout=60 적용
    r.raise_for_status()
    return r.json()

def extract_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    for v in data.values():
        if isinstance(v, list):
            for elem in v:
                if isinstance(elem, dict) and "row" in elem:
                    rows = elem["row"]
                    if isinstance(rows, list): return rows
                    if isinstance(rows, dict): return [rows]
    return []

def current_assembly_age() -> str:
    today = datetime.now(KST).date()
    base_age = 21
    base_start = date(2020, 5, 30)
    if today < base_start: return str(base_age)
    years = today.year - base_start.year
    if (today.month, today.day) < (base_start.month, base_start.day): years -= 1
    term = years // 4
    return str(base_age + max(0, term))

def bill_items() -> List[Dict[str, Any]]:
    service = os.getenv("SERVICE_SEARCH_BILL","TVBPMBILL11").strip() or "TVBPMBILL11"
    age = ASSEMBLY_AGE or "auto"
    if age.lower() == "auto": age = current_assembly_age()
    out=[]
    for kw in BILL_KEYWORDS:
        try:
            data = assembly_call(service, {"BILL_NM": kw, "pSize": 30, "AGE": age})
        except requests.exceptions.RequestException as e:
            print(f"[WARN] bill_items failed for {kw}: {e}")
            continue
        except ValueError as e:
            print(f"[WARN] bill_items parsing failed for {kw}: {e}")
            continue
        rows = extract_rows(data)
        for r in rows:
            bill_id = r.get("BILL_ID") or r.get("billId")
            if not bill_id: continue
            title = r.get("BILL_NAME") or r.get("TITLE") or ""
            if not is_env_bill(title): continue
            out.append({"bill_id": bill_id, "bill_no": r.get("BILL_NO"), "bill_name": title, "propose_dt": r.get("PROPOSE_DT"), "proc_result": r.get("PROC_RESULT")})
    seen=set(); uniq=[]
    for b in out:
        if b["bill_id"] in seen: continue
        seen.add(b["bill_id"])
        uniq.append(b)
    return uniq[:300]


# --- 메인 로직 ---
def run_web() -> None:
    require_keys()
    st = load_state()
    change_items = []
    gen_utc = now_utc_iso_ms()

    # Process Laws
    for name in LAW_NAMES:
        for law_item in law_search(name):
            info = {
                "id": law_item.get("법령ID"), "name": law_item.get("법령명한글"), 
                "date": law_item.get("공포일자"), "num": law_item.get("공포번호"), "type": law_item.get("제개정구분명")
            }
            if not info["id"]: continue
            
            key = f'{info["name"]}-{info["date"]}'
            cur_key = f'{info.get("date","")}|{info.get("num","")}|{info.get("type","")}'
            prev = st["laws"].get(key)
            status = "NEW" if not prev else ("MOD" if prev.get("status_key") != cur_key else "OK")

            if status in ("NEW", "MOD"):
                diff_url = None
                new_body = get_law_body(info["id"], "lsStmd")
                
                if status == "MOD" and prev.get("body"):
                    diff_filename = f'law_{info["id"]}_{info["date"]}.html'
                    diff_path = DIFF_DIR / diff_filename
                    
                    from_title = f'이전 버전 ({prev.get("date")} 공포)'
                    to_title = f'새 버전 ({info.get("date")} 공포)'
                    
                    diff_html = make_diff_html(prev["body"], new_body, from_title, to_title)
                    diff_path.write_text(diff_html, encoding="utf-8")
                    diff_url = f'diffs/{diff_filename}'

                change_items.append({"status": status, "kind": "법령", "title": info["name"], "date": info["date"], "id": info["id"], "diff_url": diff_url, "detected_at_utc": gen_utc})
                st["laws"][key] = {"status_key": cur_key, "body": new_body, **info}

    # Process Administrative Rules (고시)
    for query in ADMRUL_QUERIES:
        for admrul_item in admrul_search(query):
            info = {
                "id": admrul_item.get("행정규칙ID"), "name": admrul_item.get("행정규칙명"),
                "date": admrul_item.get("공포일자"), "num": admrul_item.get("공포번호")
            }
            if not info["id"]: continue

            key = f'{info["name"]}-{info["num"]}'
            cur_key = f'{info.get("date","")}|{info.get("num","")}'
            prev = st["admruls"].get(key)
            status = "NEW" if not prev else ("MOD" if prev.get("status_key") != cur_key else "OK")

            if status in ("NEW", "MOD"):
                # 현재는 행정규칙에 대한 본문 비교/Diff는 구현하지 않음 (API 명세 확인 필요)
                change_items.append({"status": status, "kind": "고시", "title": info["name"], "date": info["date"], "id": info["id"], "diff_url": None, "detected_at_utc": gen_utc})
                st["admruls"][key] = {"status_key": cur_key, **info}
    
    # Process Bills (의안)
    for bill_item in bill_items():
        key = bill_item["bill_id"]
        cur_key = f'{bill_item.get("bill_no","")}|{bill_item.get("proc_result","")}|{bill_item.get("propose_dt","")}'
        prev = st["bills"].get(key)
        status = "NEW" if not prev else ("MOD" if prev.get("status_key") != cur_key else "OK")

        if status in ("NEW", "MOD"):
            change_items.append({"status": status, "kind": "의안", "title": bill_item["bill_name"], "date": bill_item["propose_dt"], "id": bill_item["bill_id"], "diff_url": None, "detected_at_utc": gen_utc})
            st["bills"][key] = {"status_key": cur_key, **bill_item}


    if not change_items:
        print("No new changes detected. Skipping changelog update.")
        return

    # Update changelog
    changelog_path = PUBLIC_DIR / "changelog.json"
    log_data = {"items": []}
    if changelog_path.exists():
        try: log_data = json.loads(changelog_path.read_text(encoding="utf-8"))
        except Exception: pass
            
    log_data["items"] = change_items + log_data.get("items", [])
    log_data["items"] = log_data["items"][:500]
    write_json(changelog_path, log_data)
    
    write_json(PUBLIC_DIR / "health.json", {"last_success_utc": gen_utc})

    save_state(st)
    print(f"Done. Found {len(change_items)} new/modified items.")

def main():
    run_web()

if __name__ == "__main__":
    main()
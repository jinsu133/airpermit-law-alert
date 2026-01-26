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

# --- 유틸리티 함수 ---
def now_kst_iso_ms() -> str:
    return datetime.now(KST).isoformat(timespec="milliseconds")
def now_utc_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists(): return {"laws":{}, "admruls":{}, "bills":{}, "last_run": None}
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception: return {"laws":{}, "admruls":{}, "bills":{}, "last_run": None}

def save_state(st: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def require_keys() -> None:
    if not LAW_OC: raise RuntimeError("LAW_OC missing")
    if not ASSEMBLY_KEY: raise RuntimeError("ASSEMBLY_KEY missing")

def make_diff_html(old_text: str, new_text: str, from_title: str, to_title: str) -> str:
    differ = difflib.HtmlDiff(tabsize=4, wrapcolumn=80)
    return differ.make_file(old_text.splitlines(), new_text.splitlines(), from_title, to_title, context=True, numlines=5)

# --- API 호출 함수 ---
def law_search(law_name: str) -> Optional[Dict[str, Any]]:
    params = {"OC": LAW_OC, "target": "law", "type": "JSON", "query": law_name, "display": "1", "sort": "ddes"}
    try:
        r = requests.get(f"{LAW_DRF_BASE}/lawSearch.do", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("LawSearch", {}).get("law", [])
        items = items if isinstance(items, list) else ([items] if items else [])
        if not items: return None
        it = items[0]
        return {
            "id": it.get("법령ID"), "name": it.get("법령명한글"), "date": it.get("공포일자"),
            "num": it.get("공포번호"), "type": it.get("제개정구분명")
        }
    except Exception as e:
        print(f"[WARN] law_search failed: {law_name} -> {e}")
        return None

def get_law_body(law_id: str) -> str:
    if not law_id: return ""
    params = {"OC": LAW_OC, "target": "lsStmd", "type": "XML", "ID": law_id}
    try:
        r = requests.get(f"{LAW_DRF_BASE}/lawService.do", params=params, timeout=30)
        r.raise_for_status()
        # 본문은 보통 <법령내용> 태그 안에 들어있음 (정규식으로 단순 추출)
        match = re.search(r'<법령내용>(.*?)</법령내용>', r.text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except Exception as e:
        print(f"[WARN] get_law_body failed for ID {law_id}: {e}")
        return ""
        
# --- 메인 로직 ---
def run_web(out_dir: str) -> None:
    require_keys()
    st = load_state()
    change_items = []
    
    gen_utc = now_utc_iso_ms()

    # 법령 처리
    for name in LAW_NAMES:
        info = law_search(name)
        if not info or not info.get("id"): continue
        
        key = info["name"]
        cur_key = f'{info.get("date","")}|{info.get("num","")}|{info.get("type","")}'
        prev = st["laws"].get(key)
        status = "OK"
        if not prev:
            status = "NEW"
        elif prev.get("status_key") != cur_key:
            status = "MOD"
        
        if status in ("NEW", "MOD"):
            diff_url = None
            new_body = get_law_body(info["id"])
            
            if status == "MOD" and prev.get("body"):
                old_body = prev["body"]
                diff_filename = f'law_{info["id"]}_{info["date"]}.html'
                diff_path = DIFF_DIR / diff_filename
                
                from_title = f'이전 버전 ({prev.get("date")} 공포)'
                to_title = f'새 버전 ({info.get("date")} 공포)'
                
                diff_html = make_diff_html(old_body, new_body, from_title, to_title)
                diff_path.write_text(diff_html, encoding="utf-8")
                diff_url = f'diffs/{diff_filename}'

            item = {
                "status": status, "kind":"법령", "title": info["name"], 
                "date": info["date"], "id": info["id"], "diff_url": diff_url,
                "detected_at_utc": gen_utc,
            }
            change_items.append(item)
            
            # 상태 저장시 본문 내용도 포함
            st["laws"][key] = {"status_key": cur_key, "body": new_body, **info}
        
    # 변경 로그 업데이트
    changelog_path = PUBLIC_DIR / "changelog.json"
    log_data = {"items": []}
    if changelog_path.exists():
        try:
            log_data = json.loads(changelog_path.read_text(encoding="utf-8"))
        except Exception:
            pass # ignore parse error
            
    log_data["items"] = change_items + log_data.get("items", [])
    log_data["items"] = log_data["items"][:500] # 최신 500개만 유지
    write_json(changelog_path, log_data)
    
    # health.json 업데이트
    write_json(PUBLIC_DIR / "health.json", {"last_success_utc": gen_utc})

    save_state(st)
    print(f"Done. Found {len(change_items)} changes.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["web"], default="web")
    ap.add_argument("--out", default="public") # 사용하지 않지만 호환성을 위해 남겨둠
    args = ap.parse_args()
    run_web(args.out)

if __name__ == "__main__":
    main()
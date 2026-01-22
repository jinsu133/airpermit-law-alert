# -*- coding: utf-8 -*-
"""
법령/고시/의안 알림 - 정적 웹용 생성기
- web 모드: public/updates.json, public/changes.json, public/health.json 생성 + data/state.json 업데이트
- 키는 환경변수(GitHub Secrets)로만 주입 (절대 코드/파일에 하드코딩 금지)
"""

import argparse
import json
import os
import re
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = DATA_DIR / "state.json"

KST = timezone(timedelta(hours=9))
LAW_DRF_BASE = "https://www.law.go.kr/DRF"
ASSEMBLY_BASE = "https://open.assembly.go.kr/portal/openapi"

# 로컬에서만 .env 사용(레포에 커밋 금지)
if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env")

LAW_OC = os.getenv("LAW_OC", "").strip()
ASSEMBLY_KEY = os.getenv("ASSEMBLY_KEY", "").strip()
ASSEMBLY_AGE = os.getenv("ASSEMBLY_AGE", "").strip()

LAW_NAMES = [
  "대기환경보전법","대기환경보전법 시행령","대기환경보전법 시행규칙",
  "환경분야 시험·검사 등에 관한 법률","환경분야 시험 검사 등에 관한 법률",
  "환경분야 시험·검사 등에 관한 법률 시행령","환경분야 시험·검사 등에 관한 법률 시행규칙",
  "대기관리권역의 대기환경개선에 관한 특별법","대기관리권역의 대기환경개선에 관한 특별법 시행령","대기관리권역의 대기환경개선에 관한 특별법 시행규칙",
  "환경오염시설의 통합관리에 관한 법률","환경오염시설의 통합관리에 관한 법률 시행령","환경오염시설의 통합관리에 관한 법률 시행규칙",
]
ADMRUL_QUERIES = [
  "대기오염공정시험기준",
  "환경시험·검사기관 정도관리 운영등에 관한 규정",
  "환경시험 검사기관 정도관리 운영",
]
BILL_KEYWORDS = [
  "대기환경보전법",
  "환경분야 시험·검사 등에 관한 법률",
  "대기관리권역의 대기환경개선에 관한 특별법",
  "환경오염시설의 통합관리에 관한 법률",
]

def now_kst_iso_ms() -> str:
    return datetime.now(KST).isoformat(timespec="milliseconds")
def now_utc_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

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

def ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"laws":{}, "admruls":{}, "bills":{}, "last_run": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"laws":{}, "admruls":{}, "bills":{}, "last_run": None}

def save_state(st: Dict[str, Any]) -> None:
    ensure_parent(STATE_PATH)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)

def require_keys() -> None:
    if not LAW_OC:
        raise RuntimeError("LAW_OC missing (GitHub Secrets에 설정 필요)")
    if not ASSEMBLY_KEY:
        raise RuntimeError("ASSEMBLY_KEY missing (GitHub Secrets에 설정 필요)")

def law_search(law_name: str) -> Optional[Dict[str, Any]]:
    url = f"{LAW_DRF_BASE}/lawSearch.do"
    headers={"User-Agent":"law-alert/1.0"}
    params = {"OC": LAW_OC, "target":"law", "type":"json", "search": law_name, "display":"30"}
    try:
        r = requests.get(url, params=params, timeout=25, headers=headers)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        # 외부 API 오류(5xx 등) 시 스킵
        print(f"[WARN] law_search 실패: {law_name} -> {e}")
        return None
    law_container = data.get("LawSearch", {})
    raw = law_container.get("law", [])
    items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    if not items:
        return None
    it = items[0]
    return {
        "law_name": it.get("법령명한글", law_name),
        "ld": it.get("공포일자",""),
        "ln": it.get("공포번호",""),
        "reform_type": it.get("제개정구분명",""),
    }

def admrul_search(keyword: str) -> List[Dict[str, Any]]:
    url = f"{LAW_DRF_BASE}/admrulSearch.do"
    headers={"User-Agent":"law-alert/1.0"}
    params = {"OC": LAW_OC, "target":"admrul", "type":"json", "search": keyword, "display":"20"}
    r = requests.get(url, params=params, timeout=25, headers=headers)
    r.raise_for_status()
    data = r.json()
    items = (((data.get("AdmrulSearch") or {}).get("admrul")) or [])
    items = items if isinstance(items, list) else ([items] if isinstance(items, dict) else [])
    out=[]
    for it in items:
        title = it.get("행정규칙명","") or ""
        dept = it.get("소관부처명","") or ""
        # 환경부 계열만
        if dept and not any(x in dept for x in ("환경부","국립환경과학원","기후에너지환경부")):
            continue
        out.append({
            "title": title,
            "dept": dept,
            "num": it.get("고시번호","") or it.get("행정규칙ID","") or "",
            "promulgation_date": it.get("공포일자","") or "",
            "enforce_date": it.get("시행일자","") or "",
        })
    return out

def assembly_call(service: str, params: Dict[str, Any]) -> Dict[str, Any]:
    q = {"KEY": ASSEMBLY_KEY, "Type":"json", "pIndex":1}
    q.update(params)
    r = requests.get(f"{ASSEMBLY_BASE}/{service}", params=q, timeout=25)
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

def bill_items() -> List[Dict[str, Any]]:
    # 서비스: TVBPMBILL11(의안검색) 사용
    service = os.getenv("SERVICE_SEARCH_BILL","TVBPMBILL11").strip() or "TVBPMBILL11"
    age = ASSEMBLY_AGE or "auto"
    if age.lower() == "auto":
        age = current_assembly_age()
    out=[]
    for kw in BILL_KEYWORDS:
        data = assembly_call(service, {"BILL_NM": kw, "pSize": 30, "AGE": age})
        rows = extract_rows(data)
        for r in rows:
            bill_id = r.get("BILL_ID") or r.get("billId")
            if not bill_id:
                continue
            out.append({
                "bill_id": bill_id,
                "bill_no": r.get("BILL_NO") or r.get("BILLNO"),
                "bill_name": r.get("BILL_NAME") or r.get("TITLE") or "",
                "propose_dt": r.get("PROPOSE_DT") or "",
                "proc_result": r.get("PROC_RESULT") or r.get("PROC_RESULT_CD") or "",
            })
    # 중복 제거
    seen=set(); uniq=[]
    for b in out:
        if b["bill_id"] in seen:
            continue
        seen.add(b["bill_id"])
        uniq.append(b)
    return uniq[:300]

def status_from_prev(prev: Optional[Dict[str, Any]], status_key: str) -> str:
    if not prev: return "NEW"
    return "MOD" if prev.get("status_key") != status_key else "OK"

def write_json(path: Path, obj: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def run_web(out_dir: str) -> None:
    require_keys()
    st = load_state()
    all_items=[]
    change_items=[]

    # laws
    for name in LAW_NAMES:
        info = law_search(name)
        if not info:
            continue
        key = info["law_name"]
        cur_key = "|".join([info.get("ld",""), info.get("ln",""), info.get("reform_type","")])
        prev = st["laws"].get(key)
        status = status_from_prev(prev, cur_key)
        item_id = f'{info.get("ln","")}|{info.get("ld","")}|{info.get("reform_type","")}'.strip("|") or key
        item = {"status": status, "kind":"법령", "title": info.get("law_name") or name, "date": info.get("ld",""), "id": item_id}
        all_items.append(item)
        if status in ("NEW","MOD"):
            change_items.append(item.copy())
        st["laws"][key] = {"status_key": cur_key, **info}

    # admruls
    for kw in ADMRUL_QUERIES:
        for it in admrul_search(kw):
            key = f'{it.get("title","")}::{it.get("num","")}'
            cur_key = "|".join([it.get("promulgation_date",""), it.get("enforce_date",""), it.get("num","")])
            prev = st["admruls"].get(key)
            status = status_from_prev(prev, cur_key)
            item_id = f'{it.get("num","")}|{it.get("promulgation_date","")}|{it.get("enforce_date","")}'.strip("|") or key
            item = {"status": status, "kind":"고시", "title": it.get("title",""), "date": it.get("promulgation_date") or it.get("enforce_date") or "", "id": item_id}
            all_items.append(item)
            if status in ("NEW","MOD"):
                change_items.append(item.copy())
            st["admruls"][key] = {"status_key": cur_key, **it}

    # bills
    for b in bill_items():
        key = b["bill_id"]
        cur_key = "|".join([b.get("bill_no","") or "", b.get("proc_result","") or "", b.get("propose_dt","") or ""])
        prev = st["bills"].get(key)
        status = status_from_prev(prev, cur_key)
        item = {"status": status, "kind":"의안", "title": b.get("bill_name",""), "date": b.get("propose_dt",""), "id": b["bill_id"]}
        all_items.append(item)
        if status in ("NEW","MOD"):
            change_items.append(item.copy())
        st["bills"][key] = {"status_key": cur_key, **b}

    gen_kst = now_kst_iso_ms()
    gen_utc = now_utc_iso_ms()

    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    write_json(outp/"updates.json", {"generated_at_kst": gen_kst, "generated_at_utc": gen_utc, "items": all_items})
    write_json(outp/"changes.json", {"generated_at_kst": gen_kst, "generated_at_utc": gen_utc, "items": change_items})
    write_json(outp/"health.json",  {"last_success_kst": gen_kst, "last_success_utc": gen_utc})

    st["last_run"] = gen_kst
    save_state(st)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["web"], default="web")
    ap.add_argument("--out", default="public")
    args = ap.parse_args()
    run_web(args.out)

if __name__ == "__main__":
    main()

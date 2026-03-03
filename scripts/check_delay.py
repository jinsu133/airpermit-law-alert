# -*- coding: utf-8 -*-
import json, os, sys
from datetime import datetime, timedelta, timezone
KST = timezone(timedelta(hours=9))
def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return datetime.fromisoformat(s)
def main() -> int:
    out_dir = os.environ.get("OUT_DIR", "public").strip() or "public"
    threshold_min = int(os.environ.get("DELAY_THRESHOLD_MIN", "75"))
    health_path = os.path.join(out_dir, "health.json")
    if not os.path.exists(health_path):
        print(f"[DELAY] health.json not found: {health_path}", file=sys.stderr)
        return 1
    with open(health_path, "r", encoding="utf-8") as f:
        h = json.load(f)
    last_kst = h.get("last_success_kst") or ""
    if not last_kst:
        print("[DELAY] last_success_kst empty", file=sys.stderr)
        return 1
    last_dt = parse_iso(last_kst).astimezone(KST)
    now_dt = datetime.now(KST)
    diff_min = (now_dt - last_dt).total_seconds() / 60.0
    print(f"[DELAY] last_success_kst={last_dt.isoformat(timespec='milliseconds')}")
    print(f"[DELAY] now_kst={now_dt.isoformat(timespec='milliseconds')}")
    print(f"[DELAY] diff={diff_min:.2f} min, threshold={threshold_min} min")
    if diff_min > threshold_min:
        print("[DELAY] threshold exceeded -> FAIL", file=sys.stderr)
        return 1
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

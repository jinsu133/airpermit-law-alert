# Plan: Localize and Fix Law Updates Output

## 1. Requirements Analysis
- **User Complaints**:
    1.  `updates.json` seems empty or missing changes.
    2.  Status codes like `MOD`, `NEW`, `OK` are not user-friendly (Korean needed).
- **Goal**:
    - Convert internal status codes to Korean labels (e.g., `MOD` -> `변경됨`, `NEW` -> `신규`).
    - Verify why `updates` might look empty (check logic for detecting changes).

## 2. Design Changes (scripts/law_notifier.py)
### 2.1. Status Key Mapping
- Create a mapping dictionary:
    ```python
    STATUS_KO = {
        "NEW": "신규",
        "MOD": "변경",
        "OK": "유지"
    }
    ```
- Use this mapping when generating `title` or `status` field in the JSON output, OR add a new field `status_ko`.

### 2.2. "No Changes" Issue Investigation
- The script currently generates `changes.json` only when `status` is `NEW` or `MOD`.
- If the state file (`data/state.json`) is already up-to-date with the latest API data, `status` will be `OK`.
- **Action**: We need to confirm if the user *wants* to see historical changes or just *current* new changes.
- If it's for a "History View", we might need to append to a history log rather than overwriting `changes.json` every time.

## 3. Implementation Steps
1.  **Modify `law_notifier.py`**:
    - Add `status_ko` field to the output JSON items.
    - Example: `item["status_ko"] = "변경"`
2.  **Test Locally**:
    - Run the script and check `public/updates.json`.
3.  **Deploy**:
    - Commit and Push to trigger GitHub Actions.

## 4. Verification
- After CI finishes, check the live URL (via proxy or GitHub Pages branch) to see if valid Korean text appears.

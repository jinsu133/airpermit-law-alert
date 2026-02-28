# Plan: Fix Law Notifier GitHub Actions Failure

## 1. Problem Analysis
- **Symptom**: GitHub Actions build failed with `NameError: name 'bill_items_from_keyword' is not defined`.
- **Observation**:
    - The failure log in the screenshot is dated **4 days ago**.
    - The current local code (`scripts/law_notifier.py`) **does not contain** the problematic function call `bill_items_from_keyword`. It uses `bill_items()` correctly on line 296 (and defined on 208).
    - Line 217 in logging shows a completely different code structure than the current local file.
- **Conclusion**: The error log corresponds to an old version of the code. The current local code appears to have been fixed or refactored already.

## 2. Verification Strategy
- **Local Test**: Run `python scripts/law_notifier.py` locally.
    - Expected Result: Should fail with `RuntimeError: LAW_OC missing` (due to missing secrets), NOT `NameError`.
    - If this happens, it confirms the code logic is syntactically correct.
- **Remote Verification**: Check if the latest commit on GitHub matches the local code.

## 3. Action Plan
1.  **Confirm Local Health**: Verify that the local script runs without syntax errors.
2.  **Sync with GitHub**: Ensure current local changes are pushed to GitHub.
3.  **Trigger CI**: Manually re-run the GitHub Actions workflow to verify the fix with the latest code.
4.  **Monitor**: Watch the new workflow run for success.

## 4. Expected Outcome
- The GitHub Actions workflow "Generate JSON (web)" step will pass (or fail at a later stage due to API keys, but the `NameError` will be gone).

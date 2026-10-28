"""Run every test script. From the backend folder:  python -m tests.run_all
In Docker:  docker compose exec backend python -m tests.run_all
Set UNSUBVAULT_OFFLINE=1 to skip the checks that need the internet."""
import os, re, subprocess, sys

from tests import _env

MODULES = ["scan_pipeline", "bulk_unsubscribe", "spam_detection", "recovery_and_review_rules",
           "safe_senders", "spam_move", "broker_checklist", "registry_and_links",
           "sender_verification", "auth_settings_llm", "hardening"]

def main() -> int:
    total_pass = total_fail = 0
    bad = []
    for m in MODULES:
        r = subprocess.run([sys.executable, "-m", f"tests.{m}"], capture_output=True, text=True)
        summary = re.findall(r"(\d+) passed, (\d+) failed", r.stdout)
        if r.returncode != 0 or not summary:
            bad.append(m); print(f"{m}: CRASHED\n{(r.stdout + r.stderr)[-1500:]}"); continue
        p, f = map(int, summary[-1]); total_pass += p; total_fail += f
        print(f"{m}: {p} passed, {f} failed")
        for line in r.stdout.splitlines():
            if line.startswith("FAIL"):
                print("   ", line)
        if f:
            bad.append(m)
    _env.teardown()
    print(f"\nTOTAL: {total_pass} passed, {total_fail} failed" + (f"; problems in: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())

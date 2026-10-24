"""Phase 0 tests: ledger increments and refuses; no key string in anything the browser can fetch; proxy hides dotfiles."""
import json, pathlib, subprocess, sys, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import spend
from dotenv import dotenv_values
ROOT = pathlib.Path(__file__).parent; ENV = dotenv_values(ROOT.parent / ".env")

def test_ledger():
    import tempfile; spend.LEDGER = pathlib.Path(tempfile.mkdtemp()) / "spend.json"  # isolated ledger for the dry run
    spend.charge("anthropic", 0.0, count_key="dry_run", note="dry run")
    assert spend.status()["counts"]["dry_run"] == 1, "ledger did not increment"
    try:
        spend.check("anthropic", est_usd=100.0); raise AssertionError("cap not enforced")
    except spend.SpendCapExceeded: pass
    print("ledger: increments and refuses OK")

def test_no_keys_in_served_files():
    secrets = [v for v in ENV.values() if v and len(v) > 12]
    hits = []
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in (".html", ".js", ".json", ".css", ".txt", ".md", ".py") and "cache" not in p.parts:
            txt = p.read_text(errors="ignore")
            for s in secrets:
                if s in txt: hits.append(str(p))
    assert not hits, f"KEY LEAK in served files: {hits}"
    print(f"no key strings in {ROOT} files OK")

def test_proxy_hides_dotfiles(port=8765):
    for path in ("/../.env", "/.env", "/..%2F.env"):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5); body = r.read()
            assert b"API_KEY" not in body, f"proxy served secrets at {path}"
        except urllib.error.HTTPError as e:
            assert e.code in (403, 404), f"unexpected {e.code} for {path}"
    print("proxy refuses dotfiles and traversal OK")

if __name__ == "__main__":
    test_ledger(); test_no_keys_in_served_files(); test_proxy_hides_dotfiles(); print("PHASE0 TESTS PASSED")

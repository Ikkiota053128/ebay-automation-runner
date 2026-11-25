"""GAS の受け口が正しく返事をするか見る（読むだけ・URL と鍵は出さない）。11/25 GAS のコードのまちがいの確認"""
import os, re, urllib.parse, urllib.request
url, tok = os.environ.get("GAS_WEBAPP_URL", "").strip(), os.environ.get("GAS_SEND_TOKEN", "").strip()
print("URL の形：", "exec" if url.endswith("/exec") else ("dev" if url.endswith("/dev") else "そのほか"))
for page in ("ghcands", "ghmodels"):
    q = url + "?" + urllib.parse.urlencode({"page": page, "token": tok, "hours": 1})
    try:
        with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as f:
            b = f.read().decode("utf-8", "replace")
            ct = f.headers.get("Content-Type")
    except Exception as e:
        print(page, "エラー", str(e)[:200]); continue
    b = b.replace(tok, "***") if tok else b
    t = re.sub(r"<[^>]+>", " ", b)
    t = re.sub(r"\s+", " ", t)
    print(page, ct, "長さ", len(b), "頭：", t[:400])

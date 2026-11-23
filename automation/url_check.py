"""台帳の仕入元URLが、本当に同じ品のページかを点検する（読むだけ・手で動かす）。
11/24 07:34 オーナー「1〜4やって」：SP-1 の事故（台帳のURLが香水のページで、在庫の監視が「ある」と判断していた）の再発を防ぐ。
- 出品中の品ごとに、仕入れ先の商品名（楽天は公式APIの itemName、ほかはページの og:title / title）を読み、
  台帳のタイトルの型番（price_adjust.model_of・無ければタイトルの2語目）が商品名か説明に入っているかを見る。
- 結果：合う／合わない（型番が無い）／読めない（エラーの全文）／対象外（メルカリ・Amazon・URLなし）。
- メルカリ・Amazon のページは開かない。同じサイトは3秒以上あける。
- 結果は data/判定/URLの点検.json。台帳・eBay は変えない。"""
import os, re, sys, time, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, save_json, read_ledger
from stock_watch import fetch, _rk_call, _rk_norm
from price_adjust import model_of
from title_make import norm

RP = os.path.join(ROOT, "data", "判定", "URLの点検.json")
T_END = time.time() + 60 * 25


def nf(s):
    return unicodedata.normalize("NFKC", s or "")


def rakuten_name(url):
    key = _rk_norm(url)
    rid, acc = os.environ.get("RAKUTEN_APP_ID", "").strip(), os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
    relay, tok = os.environ.get("RAKUTEN_RELAY_URL", "").strip(), os.environ.get("RAKUTEN_RELAY_TOKEN", "").strip()
    if not (key and rid and acc and relay):
        return None, "楽天の鍵が無い"
    q = {"format": "json", "formatVersion": 2, "applicationId": rid, "availability": 0, "itemCode": "%s:%s" % key, "hits": 1}
    req_q = dict(q)
    j, err = _rk_call(req_q, relay, acc, tok)
    if err:
        return None, err + " ／ 送った itemCode=%s:%s" % key
    for it in (j or {}).get("items") or (j or {}).get("Items") or []:
        it = it.get("Item", it)
        return "%s\n%s" % (it.get("itemName", ""), (it.get("itemCaption", "") or "")[:3000]), ""
    return None, "楽天API：0件（商品が消えた可能性）"


def page_name(url):
    code, html = fetch(url)
    if code != 200 or not html:
        return None, "HTTP %s" % code
    html = html.replace("\\u002F", "/")
    names = re.findall(r'<meta[^>]+property="og:title"[^>]+content="([^"]{3,400})"', html)
    names += re.findall(r"<title[^>]*>([^<]{3,400})</title>", html)
    desc = re.findall(r'<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]{3,3000})"', html)
    if not names:
        return None, "商品名が読めない"
    return "%s\n%s" % (" / ".join(names[:2]), " ".join(desc[:2])), ""


def main():
    rows = [r for r in read_ledger() if r.get("状態") == "出品中"]
    out = {"時刻": jst(), "合う": [], "合わない": [], "読めない": [], "対象外": [], "時間切れ": False}
    last = {}
    for r in rows:
        url, title = (r.get("仕入元URL") or "").strip(), r.get("タイトル") or ""
        base = {"SKU": r["SKU"], "タイトル": title[:70], "URL": url, "売値": r.get("売値(ドル)"), "仕入値": r.get("仕入値(円)")}
        if not url or re.search(r"mercari|amazon\.", url):
            out["対象外"].append(dict(base, 理由="URLなし" if not url else "メルカリ・Amazon（開かない）"))
            continue
        if time.time() > T_END:
            out["時間切れ"] = True
            break
        md = model_of(title) or (title.split(" ")[1] if len(title.split(" ")) > 1 else "")
        host = re.sub(r"https?://([^/]+).*", r"\1", url)
        wait = 3 - (time.time() - last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            name, err = rakuten_name(url) if "item.rakuten.co.jp" in url else page_name(url)
        except Exception as e:
            name, err = None, str(e)[:300]
        last[host] = time.time()
        if not name:
            out["読めない"].append(dict(base, エラー=err))
            continue
        head = nf(name).split("\n")[0][:200]
        m = norm(md)
        if len(m) >= 3 and m in norm(nf(name)):
            out["合う"].append(dict(base, 型番=md))
        else:
            out["合わない"].append(dict(base, 型番=md, 仕入れ先の商品名=head))
    save_json(RP, out)
    print("合う", len(out["合う"]), "合わない", len(out["合わない"]), "読めない", len(out["読めない"]), "対象外", len(out["対象外"]), "時間切れ", out["時間切れ"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

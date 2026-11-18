"""eBay の出品の上限を読む（Account API getPrivileges・読むだけ）。結果は data/上限/ に書いて知らせる"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, now, notify, save_json, read_ledger, num

eb = Ebay()
out = {"時刻": jst()}
try:
    _, j = eb.call("GET", "/sell/account/v1/privilege")
    out["eBayの返事"] = j
except EbayError as e:
    out["エラー"] = err_text(e)
led = read_ledger()
act = [r for r in led if r.get("状態") == "出品中"]
out["台帳の出品中"] = {"件数": len(act), "合計ドル": round(sum(num(r.get("売値(ドル)")) or 0 for r in act), 2)}
save_json(os.path.join(ROOT, "data", "上限", now().strftime("%Y%m%d_%H%M%S") + ".json"), out)
sl = (out.get("eBayの返事") or {}).get("sellingLimit") or {}
msg = "【出品の上限】%s eBay：%s／件数 %s。台帳の出品中 %d品・$%s" % (jst(), (sl.get("amount") or {}).get("value", "?") + " " + (sl.get("amount") or {}).get("currency", ""),
                                                          sl.get("quantity", "?"), len(act), out["台帳の出品中"]["合計ドル"])
print(msg if "エラー" not in out else msg + "\n" + out["エラー"])
notify(msg)

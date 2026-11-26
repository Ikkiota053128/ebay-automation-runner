"""offerId の無い（Trading API で出した）出品を終える（手で動かす）。
11/26 22:39 オーナー「教科書通りやって」：在庫ゼロの個人の1点物のうち、offerId が無くて withdraw できない品を EndFixedPriceItem で終える。
- data/判定/終える_旧出品.json：{"本番": false, "SKU": [...]}。台帳の eBayの出品ID を終え、台帳を「終了」に。もう終わっている品も「終了」に。
- 結果は data/判定/終える_旧出品_結果.json。"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger

P = os.path.join(ROOT, "data", "判定", "終える_旧出品.json")
cfg = load_json(P, {"本番": False, "SKU": []})
live = bool(cfg.get("本番"))
by = {r["SKU"]: r for r in read_ledger()}
eb = Ebay()
out = {"時刻": jst(), "本番": live, "終えた": [], "もう終わっていた": [], "予定": [], "失敗": []}
rows = []
for sku in cfg.get("SKU") or []:
    r = by.get(sku)
    if not r or not r.get("eBayの出品ID"):
        out["失敗"].append({"SKU": sku, "エラー": "台帳に出品IDが無い"})
        continue
    if not live:
        out["予定"].append(sku)
        continue
    try:
        x = eb.trading("EndFixedPriceItem", "<ItemID>%s</ItemID><EndingReason>NotAvailable</EndingReason>" % r["eBayの出品ID"])
        ack = (re.search(r"<Ack>(\w+)</Ack>", x) or [None, ""])[1]
        if ack in ("Success", "Warning"):
            out["終えた"].append(sku)
        elif re.search(r"already been closed|has ended|already ended", x, re.I):
            out["もう終わっていた"].append(sku)
        else:
            raise RuntimeError("・".join(re.findall(r"<LongMessage>([^<]*)</LongMessage>", x))[:300])
        rows.append({"SKU": sku, "状態": "終了", "メモ": ((r.get("メモ") or "") + "・%s 在庫ゼロの個人の1点物なので終えた（教科書 5章）" % jst())[:500]})
    except (EbayError, RuntimeError) as e:
        out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:300] if isinstance(e, EbayError) else str(e)})
    time.sleep(0.5)
if rows:
    save_ledger(rows, ["状態", "メモ"], "旧出品を終える")
if live:
    cfg["本番"] = False
    cfg["SKU"] = [s for s in cfg.get("SKU") or [] if s not in {x["SKU"] for x in rows}]
    save_json(P, cfg)
save_json(os.path.join(ROOT, "data", "判定", "終える_旧出品_結果.json"), out)
print("本番" if live else "ドライラン", "終えた", len(out["終えた"]), "もう終わっていた", len(out["もう終わっていた"]), "予定", len(out["予定"]), "失敗", len(out["失敗"]))

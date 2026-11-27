"""届いたベストオファー（値下げの申し込み）を数える（読むだけ）。11/28 08:01 オーナー「オファーが今まできたことがない。なぜ？」
Trading GetBestOffers（出品ごと）で、出品中の品に来たオファー（受けた・断った・自動で断った・期限切れ）を数える。結果は data/判定/オファーの調べ.json"""
import os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, jst, read_ledger, save_json
eb = Ebay()
rows = [r for r in read_ledger() if r.get("eBayの出品ID") and r.get("状態") in ("出品中", "売れた", "在庫ゼロ")]
cnt, items, err = collections.Counter(), [], collections.Counter()
for r in rows:
    x = eb.trading("GetBestOffers", "<ItemID>%s</ItemID><BestOfferStatus>All</BestOfferStatus>" % r["eBayの出品ID"])
    ack = (re.search(r"<Ack>(\w+)</Ack>", x) or [None, ""])[1]
    if ack not in ("Success", "Warning"):
        err[(re.search(r"<ShortMessage>([^<]*)", x) or [None, "?"])[1][:60]] += 1
        continue
    for st in re.findall(r"<BestOffer>.*?<Status>(\w+)</Status>.*?</BestOffer>", x, re.S):
        cnt[st] += 1
        items.append({"SKU": r["SKU"], "状態": st})
save_json(os.path.join(ROOT, "data", "判定", "オファーの調べ.json"), {"時刻": jst(), "見た出品": len(rows), "オファー": dict(cnt), "品": items[:200], "エラー": dict(err)})
print("見た", len(rows), "オファー", dict(cnt), "エラー", dict(err.most_common(3)))

"""古い出品に SKU を付ける（Trading ReviseFixedPriceItem・SKU だけ変える）。SKU が無いと Inventory API へ移せないため（設計書 13章）。
- 対象：台帳の「要付与-<出品ID>」・出品中・ゲーム／キャラクター（決めごとA）でない品。新しい SKU は「OLD-<出品ID>」。
- eBay の返事（Ack）を1件ずつ見る。成功したら台帳に新しい SKU の行を足し、古い行は「終了」（行は消さない・メモに付け替え先）。
- そのあと 今の出品の移行（migrate.py）が OLD- の行を移す。"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Ebay, jst, notify, read_ledger, save_ledger, timetable, write_run, mark_started, COLS
from migrate import RULE_OUT

NAME = "SKUを付ける"


def main():
    tt = timetable(NAME)
    live = bool(tt.get("実行", True))
    cap = int(tt.get("1回の上限_件", 100))
    mark_started(NAME)
    eb = Ebay()
    if not eb.ready():
        write_run(NAME, False, 0, 1)
        return 0
    led = read_ledger()
    have = {r["SKU"] for r in led}
    todo = [r for r in led if r["SKU"].startswith("要付与-") and r.get("状態") == "出品中" and r.get("eBayの出品ID")][:cap]
    ok, bad, rows = [], [], []
    for r in todo:
        iid = r["eBayの出品ID"]
        new = "OLD-" + iid
        if new in have:
            continue
        if live:
            x = eb.trading("ReviseFixedPriceItem", "<Item><ItemID>%s</ItemID><SKU>%s</SKU></Item>" % (iid, new))
            ack = (re.search(r"<Ack>(\w+)</Ack>", x) or [None, ""])[1]
            if ack not in ("Success", "Warning"):
                msgs = re.findall(r"<LongMessage>([^<]*)</LongMessage>", x)
                if any("ended" in m.lower() for m in msgs):   # eBay ではもう終わっている → 台帳を「終了」に
                    rows.append({"SKU": r["SKU"], "状態": "終了", "メモ": (r.get("メモ", "") + "・%s eBayではもう終わっていた" % jst())[:500]})
                    continue
                bad.append("%s %s" % (iid, " / ".join(msgs)[:200]))
                continue
            time.sleep(0.5)
        n = {c: r.get(c, "") for c in COLS}
        n.update({"SKU": new, "メモ": (r.get("メモ", "") + "・%s SKUを付けた（もとは %s）" % (jst(), r["SKU"]))[:500]})
        rows.append(n)
        rows.append({"SKU": r["SKU"], "状態": "終了", "メモ": (r.get("メモ", "") + "・%s SKU %s を付けたので、この行は終わり（同じ出品）" % (jst(), new))[:500]})
        ok.append(new)
    if live and rows:
        save_ledger(rows, ["状態", "メモ"], NAME)
    msg = "【SKUを付ける】%s %s：%d品にSKUを付けた%s" % (jst(), "本番" if live else "ドライラン", len(ok), ("／できなかった %d品：%s" % (len(bad), " / ".join(bad[:5]))) if bad else "")
    print(msg)
    notify(msg)
    write_run(NAME, not bad, len(ok), len(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())

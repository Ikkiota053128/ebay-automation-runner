"""同じ型番の重複出品を終える（11/19 7:12 オーナー「今後型番ごとに1品だけ残して！」・教科書：同じ型番は1つの出品に実績を積む）。手で動かす。DEDUPE_LIVE=1 のときだけ終える。
もと：data/上限/eBayの出品中.json（slow_list.py）。在庫ありの出品を型番でまとめ、ウォッチの多い品 → 古い品 を1つ残し、ほかを終える。
終え方：台帳に offerId がある品は withdrawOffer（オファーは残る）、ない品は EndFixedPriceItem。台帳は「終了」に。"""
import collections, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, now, notify, load_json, save_json, read_ledger, save_ledger, write_run, mark_started
from price_adjust import model_of

NAME = "重複の出品を終える"


def key(title):
    md = model_of(title)
    k = re.sub(r"[^A-Z0-9]", "", (md or "").upper())
    return k if len(k) >= 4 and re.search(r"\d", k) and re.search(r"[A-Z]", k) else None


def main():
    live = os.environ.get("DEDUPE_LIVE") == "1"
    mark_started(NAME)
    eb = Ebay()
    items = list({i["出品ID"]: i for i in load_json(os.path.join(ROOT, "data", "上限", "eBayの出品中.json"), {}).get("品", [])}.values())
    led = read_ledger()
    by_id = collections.defaultdict(list)
    for r in led:
        by_id[r.get("eBayの出品ID", "")].append(r)
    grp = collections.defaultdict(list)
    for i in items:
        if i["在庫"] > 0 and key(i["タイトル"]):
            grp[key(i["タイトル"])].append(i)
    end = []
    for k, v in grp.items():
        if len(v) < 2:
            continue
        v.sort(key=lambda i: (-i["ウォッチ"], i["始まり"]))
        for i in v[1:]:
            end.append(dict(i, 型番=k, 残す=v[0]["出品ID"]))
    done, bad, rows = [], [], []
    if live:
        for i in end:
            rs = by_id.get(i["出品ID"], [])
            off = next((r.get("offerId") for r in rs if r.get("offerId")), "")
            try:
                if off:
                    eb.call("POST", "/sell/inventory/v1/offer/%s/withdraw" % off, {})
                else:
                    x = eb.trading("EndFixedPriceItem", "<ItemID>%s</ItemID><EndingReason>NotAvailable</EndingReason>" % i["出品ID"])
                    if (re.search(r"<Ack>(\w+)</Ack>", x) or [None, ""])[1] not in ("Success", "Warning") and "already been closed" not in x:
                        raise RuntimeError("・".join(re.findall(r"<LongMessage>([^<]*)</LongMessage>", x))[:300])
                done.append(i)
                for r in rs:
                    rows.append({"SKU": r["SKU"], "状態": "終了", "メモ": (r.get("メモ", "") + "・%s 重複で終えた（型番 %s・残したのは %s）" % (jst(), i["型番"], i["残す"]))[:500]})
            except (EbayError, RuntimeError) as e:
                bad.append((i["出品ID"], err_text(e)[:300] if isinstance(e, EbayError) else str(e)))
            time.sleep(0.5)
        if rows:
            save_ledger(rows, ["状態", "メモ"], NAME)
    rep = {"時刻": jst(), "本番": live, "重複の型番": len({i["型番"] for i in end}), "終える": [{k: i[k] for k in ("出品ID", "SKU", "値段", "ウォッチ", "始まり", "型番", "残す", "タイトル")} for i in end],
           "終えた": len(done), "失敗": bad}
    save_json(os.path.join(ROOT, "data", "移行", "重複の出品_" + now().strftime("%Y%m%d_%H%M%S") + ".json"), rep)
    msg = "【重複の出品】%s %s：重複の型番 %d・終える %d品（$%s）%s" % (jst(), "本番" if live else "ドライラン", rep["重複の型番"], len(end),
                                                         format(round(sum(i["値段"] for i in end)), ","), ("／終えた %d・失敗 %d" % (len(done), len(bad))) if live else "")
    print(msg)
    notify(msg)
    write_run(NAME, not bad, len(done), len(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())

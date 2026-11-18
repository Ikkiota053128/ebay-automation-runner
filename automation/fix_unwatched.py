"""見回られていない出品を直す（11/18 22:07 オーナー「AとCでお願いします」）。手で動かす。FIX_LIVE=1 のときだけ eBay と台帳を変える（それ以外はドライラン）。

もと：data/上限/eBayの出品中.json（slow_list.py が eBay から読んだ出品中の全部）と台帳。
対象：eBay で在庫ありなのに、台帳に無い品・台帳では「終了」の品。
C：終える（EndFixedPriceItem）＝ 決めごとA（キャラクター・ゲームなど）／同じ商品名の2つ目以降（重複）／出してから30日以上でウォッチ0。
A：残りを台帳に「出品中」で入れる（仕入元は GAS の出品作成から・v674 page=srcmap）。そのあと 今の出品の移行（migrate.py）が Inventory API へ移し、
   在庫の監視・値段の調整に乗る。SKU の無い品は「要付与-<出品ID>」で入れる（SKUを付ける add_sku.py が付ける）。
"""
import collections, datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, jst, now, notify, load_json, save_json, read_ledger, save_ledger, settings, write_run, mark_started
from stock_watch import kind_of
from migrate import RULE_OUT as RULE_OUT_M
import judge

NAME = "見回られていない出品を直す"


def srcmap():
    url, tok = os.environ.get("GAS_WEBAPP_URL", "").strip(), os.environ.get("GAS_SEND_TOKEN", "").strip()
    q = url + "?" + urllib.parse.urlencode({"page": "srcmap", "token": tok})
    d = json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "ebay-automation"}), timeout=300).read().decode("utf-8"))
    return {x["id"]: x for x in d.get("items", [])}


def main():
    live = os.environ.get("FIX_LIVE") == "1"
    mark_started(NAME)
    cfg = settings()
    eb = Ebay()
    items = load_json(os.path.join(ROOT, "data", "上限", "eBayの出品中.json"), {}).get("品", [])
    led = read_ledger()
    by_id = collections.defaultdict(list)
    for r in led:
        by_id[r.get("eBayの出品ID", "")].append(r)
    skus = {r["SKU"]: r for r in led}
    today = now().date()
    tgt = []
    for i in items:
        if i["在庫"] <= 0:
            continue
        rs = by_id.get(i["出品ID"], [])
        if not rs or not any(r.get("状態") in ("出品中", "在庫ゼロ", "売れた") for r in rs):
            tgt.append(i)
    # C：終える品
    seen_title, end, keep = {}, [], []
    for i in sorted(tgt, key=lambda x: x["始まり"]):
        try:
            days = (today - dt.date.fromisoformat(i["始まり"])).days
        except Exception:
            days = 0
        t = re.sub(r"\s+", " ", i["タイトル"].lower()).strip()
        why = ""
        if judge.RULE_OUT.search(i["タイトル"]) or RULE_OUT_M.search(i["タイトル"]):
            why = "決めごとA（キャラクター・ゲームなど）"
        elif t in seen_title:
            why = "重複（同じ商品名の %s が出品中）" % seen_title[t]
        elif days >= 30 and i["ウォッチ"] == 0:
            why = "出してから%d日・ウォッチ0" % days
        if why:
            end.append(dict(i, 理由=why))
        else:
            seen_title.setdefault(t, i["出品ID"])
            keep.append(i)
    # 台帳に出品中のものとも重複を見る（台帳の出品中と同じ商品名の品は終える）
    live_titles = {re.sub(r"\s+", " ", (r.get("タイトル") or "").lower()).strip() for r in led if r.get("状態") == "出品中"}
    k2 = []
    for i in keep:
        if re.sub(r"\s+", " ", i["タイトル"].lower()).strip() in live_titles:
            end.append(dict(i, 理由="重複（台帳の出品中に同じ商品名）"))
        else:
            k2.append(i)
    keep = k2
    # A：台帳に入れる
    try:
        sm = srcmap()
    except Exception as e:
        sm = None
        print("GAS の仕入元を読めなかった（v674 を貼ったか）：", type(e).__name__)
    rows, skip = [], []
    for i in keep:
        s = (sm or {}).get(i["出品ID"], {})
        sku = i["SKU"] or ("要付与-" + i["出品ID"])
        old = skus.get(sku)
        if old and old.get("eBayの出品ID") not in ("", i["出品ID"]):
            skip.append((i["出品ID"], "同じSKUが台帳の別の出品にある（%s）" % sku))
            continue
        if sm is not None and not s.get("src"):
            skip.append((i["出品ID"], "GAS の出品作成に仕入元が無い"))
        row = {"SKU": sku, "eBayの出品ID": i["出品ID"], "仕入元URL": s.get("src", ""), "仕入元の種類": kind_of(s.get("src", ""), cfg),
               "仕入値(円)": s.get("cost", ""), "出品時の海外送料(円)": s.get("ship", ""), "売値(ドル)": "%.2f" % i["値段"], "状態": "出品中",
               "出品日": i["始まり"], "タイトル": i["タイトル"], "手数料率": s.get("frate", ""), "関税率": "", "固定費(円)": "",
               "国内送料(円)": s.get("dom", ""), "為替": s.get("fx", ""),
               "メモ": ((old or {}).get("メモ", "") + "・%s 見回られていない出品を台帳に（GASの出品）" % jst())[:500]}
        rows.append(row)
    ended, end_bad = [], []
    if live:
        for i in end:
            x = eb.trading("EndFixedPriceItem", "<ItemID>%s</ItemID><EndingReason>NotAvailable</EndingReason>" % i["出品ID"])
            ack = (re.search(r"<Ack>(\w+)</Ack>", x) or [None, ""])[1]
            if ack in ("Success", "Warning") or "already been closed" in x or "has been ended" in x.lower():
                ended.append(i)
            else:
                end_bad.append((i["出品ID"], "・".join(re.findall(r"<LongMessage>([^<]*)</LongMessage>", x))[:300]))
            time.sleep(0.5)
        end_rows = []
        for i in ended:
            for r in by_id.get(i["出品ID"], []):
                end_rows.append({"SKU": r["SKU"], "状態": "終了", "メモ": (r.get("メモ", "") + "・%s 終えた：%s" % (jst(), i["理由"]))[:500]})
        if end_rows:
            save_ledger(end_rows, ["状態", "メモ"], NAME)
        if rows and sm is not None:
            save_ledger(rows, list(rows[0].keys()), NAME)
    rep = {"時刻": jst(), "本番": live, "対象": len(tgt), "終える": [{k: i[k] for k in ("出品ID", "SKU", "値段", "理由", "タイトル")} for i in end],
           "終えた": len(ended), "終えられなかった": end_bad, "台帳に入れる": len(rows), "入れなかった・注意": skip}
    save_json(os.path.join(ROOT, "data", "移行", "見回られていない出品_" + now().strftime("%Y%m%d_%H%M%S") + ".json"), rep)
    why = collections.Counter(re.sub(r"（.*|\d+日.*", "", i["理由"]) for i in end)
    msg = "【見回られていない出品】%s %s：対象 %d品／終える %d品・$%s（%s）／台帳に入れる %d品%s%s" % (
        jst(), "本番" if live else "ドライラン", len(tgt), len(end), format(round(sum(i["値段"] for i in end)), ","),
        "・".join("%s %d" % kv for kv in why.most_common()), len(rows),
        ("／終えた %d・失敗 %d" % (len(ended), len(end_bad))) if live else "", "／注意 %d品（仕入元が分からない等）" % len(skip) if skip else "")
    print(msg)
    notify(msg)
    write_run(NAME, not end_bad, len(ended) + len(rows), len(end_bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())

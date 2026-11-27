"""売れにくい出品の一覧（読むだけ）：GitHubに移した出品中の品を、同じ型番・同じ状態の eBay の相場と比べる。
相場の基準は GAS（quotePrice_）と同じ：外れ値・付属品を外したあとの「最安・2番目・真ん中」の一番高い値段。
今の値段がその 1.4倍 を超える品を data/上限/終える候補.json に書く（終えるのは別。オーナーの承認のあと）"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, now, notify, save_json, read_ledger, is_target, num, settings
from price_adjust import model_of
import judge


def market(act0):
    act0 = sorted(x for x in act0 if x > 0)
    if not act0:
        return None
    med = act0[len(act0) // 2]
    import judge
    _t = judge.textbook_outlier(act0)
    if _t is not None:
        return {"最安": _t[0], "2番目": _t[1] if len(_t) >= 2 else 0, "真ん中": med, "基準": max(med, (_t[1] if len(_t) >= 2 else 0), _t[0]), "件数": len(act0)}
    mid = act0[(len(act0) - 1) // 2] if len(act0) >= 3 else 0
    act = [x for x in act0 if x >= mid * 0.5] if mid > 0 else act0[:]
    top = act0[len(act0) // 2:]
    um = top[(len(top) - 1) // 2] if top else 0
    ref = max(um, med)
    if ref > 0 and act:
        act = [x for x in act if x >= ref * 0.35] or [med]
    if len(act0) >= 5:
        act = [x for x in act if x >= med * 0.65] or [med]
        dr = 0
        while len(act) >= 3 and dr < 2 and act[0] < act[1] * 0.85 and act[0] < med * 0.7:
            act, dr = act[1:], dr + 1
    L = act[0]
    L2 = act[1] if len(act) >= 2 else 0
    return {"最安": L, "2番目": L2, "真ん中": med, "基準": max(med, L2 or 0, L), "件数": len(act0)}


def main():
    eb, cfg = Ebay(), settings()
    me = cfg.get("店", {}).get("セラー名", "").lower()
    led = read_ledger()
    my_ids = {r.get("eBayの出品ID") for r in led}
    rows = [r for r in led if is_target(r) and r.get("状態") == "出品中"]
    out, nocomp = [], 0
    for r in rows:
        md = model_of(r.get("タイトル"))
        if not md:
            nocomp += 1
            continue
        cond = int(num(r.get("eBayの状態ID")) or 3000)
        try:
            cat = ""
            try:   # 自分の出品と同じカテゴリの競合だけ（付属品のカテゴリを混ぜない）
                o = [x for x in eb.offers_of(r["SKU"]) if x.get("offerId") == r.get("offerId")]
                cat = str((o[0] if o else {}).get("categoryId") or "")
            except EbayError:
                pass
            m = market(judge.comps(eb, md, cond, me, my_ids, cat=cat or None))
        except EbayError as e:
            print("検索エラー", err_text(e)[:200])
            break
        if not m:
            nocomp += 1
            continue
        p = num(r.get("売値(ドル)")) or 0
        x = round(p / m["基準"], 2)
        if x > 1.4:
            out.append({"SKU": r["SKU"], "eBayの出品ID": r.get("eBayの出品ID"), "offerId": r.get("offerId"), "タイトル": r.get("タイトル", "")[:80],
                        "今の値段": p, "相場の基準": m["基準"], "倍率": x, "カテゴリ": cat, "最安": m["最安"], "真ん中": m["真ん中"], "競合の数": m["件数"]})
        time.sleep(0.3)
    out.sort(key=lambda o: -o["倍率"])
    save_json(os.path.join(ROOT, "data", "上限", "終える候補.json"), {"時刻": jst(), "見た": len(rows), "競合なし・型番なし": nocomp, "候補": out})
    msg = "【売れにくい出品】%s 出品中 %d品を見た → 相場の1.4倍超 %d品（合計 $%.0f）・2倍超 %d品・競合なし %d品（記録だけ）" % (
        jst(), len(rows), len(out), sum(o["今の値段"] for o in out), sum(1 for o in out if o["倍率"] > 2), nocomp)
    print(msg)
    notify(msg)


if __name__ == "__main__":
    main()

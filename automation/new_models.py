"""新品の型番を型番リストに足す（試し・手で動かす）。11/21 13:25 オーナー「はい、やります。…教科書通に動いて」
教科書：Amazon・楽天市場・Yahoo!ショッピングは新品系で在庫が安定＝無在庫向き。今の型番リストは中古向きなので、今売っている新品の型番を足して試す。
- 候補（下の CANDS）を eBay（Browse・即決・新品・送料込みでアメリカ向け）で数え、同じ型番の新品が3件以上・中央値 $60〜$1,000 の型番だけ足す。
- 付属品・ジャンク・決めごとA（ゲーム・キャラクターなど）・大きい品は足さない。GAS の型番リストと GitHub の追加にもう有る型番は足さない。
- 足すのは上限50型番（時刻表 型番リストを育てる → 新品の試し_型番 で変えられる）。足した型番は data/型番リスト/追加.json（cond は「新品」）。
- 店の地引網（楽天・Yahoo!ショッピング）とフリマの地引網が、次の回からこの型番も探す。判定・値付けは今までどおり。"""
import json, os, re, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, timetable, browse_stopped
from price_adjust import JUNK, BOOK, REF_ACC, ACC
from flea_sweep import gas_get_models
import judge

CANDS = [
    ("Casio", "GA-2100-1A1"), ("Casio", "GA-B2100-1A"), ("Casio", "GA-2100-4A"), ("Casio", "GW-M5610U-1"), ("Casio", "GW-M5610U-1B"),
    ("Casio", "DW-5600E-1"), ("Casio", "DW-5600BB-1"), ("Casio", "GA-110-1B"), ("Casio", "GA-700-1B"), ("Casio", "GBD-200-1"),
    ("Casio", "GW-B5600-2"), ("Casio", "GMW-B5000D-1"), ("Casio", "GA-B001-1A"), ("Casio", "GBM-2100A-1A3"), ("Casio", "GW-9400-1"),
    ("Casio", "GWG-2000-1A3"), ("Casio", "GST-B400D-1A"), ("Casio", "GM-2100-1A"), ("Casio", "GM-B2100D-1A"), ("Casio", "DW-6900U-1"),
    ("Casio", "PRW-35-1A"), ("Casio", "PRG-340-1"), ("Casio", "OCW-T200S-1A"), ("Casio", "GW-M5610-1"),
    ("Seiko", "SRPD55"), ("Seiko", "SRPD51"), ("Seiko", "SRPE93"), ("Seiko", "SPB143"), ("Seiko", "SPB317"), ("Seiko", "SSK001"),
    ("Seiko", "SRPE51"), ("Seiko", "SBDC101"), ("Citizen", "BN0151-09L"), ("Citizen", "BM8475-26E"), ("Citizen", "NJ0150-81E"),
    ("Orient", "RA-AA0003R"), ("Orient", "RA-AC0F02B"),
    ("BOSS", "DS-1"), ("BOSS", "SD-1"), ("BOSS", "DD-8"), ("BOSS", "RC-5"), ("BOSS", "TU-3"), ("BOSS", "BD-2"), ("BOSS", "OD-3"),
    ("BOSS", "CE-2W"), ("BOSS", "DS-1W"), ("BOSS", "BD-2W"), ("BOSS", "SD-1W"), ("BOSS", "MT-2W"), ("BOSS", "DD-3T"), ("BOSS", "RV-6"),
    ("BOSS", "GE-7"), ("BOSS", "NS-2"), ("BOSS", "PH-3"), ("BOSS", "DC-2W"), ("BOSS", "DM-2W"), ("BOSS", "BB-1X"), ("BOSS", "DS-2"),
    ("Korg", "PB-01"), ("Korg", "volca bass"), ("Korg", "volca keys"), ("Korg", "volca sample2"), ("Roland", "SP-404MKII"),
    ("Fujifilm", "instax mini 12"), ("Fujifilm", "instax mini Evo"), ("Fujifilm", "instax SQUARE SQ1"), ("Fujifilm", "instax Wide 400"),
    ("Sigma", "18-50mm F2.8 DC DN"), ("Sigma", "56mm F1.4 DC DN"), ("Sigma", "30mm F1.4 DC DN"), ("Tamron", "B070"), ("Tamron", "A063"),
    ("Sony", "WH-1000XM5"), ("Sony", "WF-1000XM5"), ("Sony", "WH-CH720N"), ("Sony", "MDR-7506"), ("Sony", "NW-A306"), ("Sony", "NW-ZX707"),
    ("Audio-Technica", "ATH-M50x"), ("Audio-Technica", "ATH-M50xBT2"), ("Audio-Technica", "AT-LP60X"), ("Audio-Technica", "ATH-R70x"),
    ("Audio-Technica", "AT-LP120XUSB"),
]


def key(s):
    return re.sub(r"[^0-9A-Z]", "", str(s).upper())


def main():
    tt = timetable("型番リストを育てる")
    cap = int(tt.get("新品の試し_型番", 50))
    eb = Ebay()
    if not eb.ready() or browse_stopped():
        print("eBay の鍵が無いか、検索を止めている")
        return 0
    have = set()
    try:
        have = {key(m.get("model")) for m in gas_get_models()}
    except Exception:
        pass
    add_p = os.path.join(ROOT, "data", "型番リスト", "追加.json")
    add = load_json(add_p, [])
    have |= {key(a.get("model")) for a in add}
    res, out = [], []
    for mk, md in CANDS:
        if key(md) in have:
            res.append({"型番": md, "結果": "もうリストにある"})
            continue
        try:
            items = eb.browse("%s %s" % (mk, md), "buyingOptions:{FIXED_PRICE},conditionIds:{1000}", limit=100)
        except EbayError as e:
            res.append({"型番": md, "結果": "検索できなかった " + err_text(e)[:80]})
            continue
        ps = []
        for it in items:
            t = it.get("title", "")
            if key(md) not in key(t) or JUNK.search(t) or BOOK.search(t) or REF_ACC.search(t) or ACC.search(t) or judge.RULE_OUT.search(t):
                continue
            p = float((it.get("price") or {}).get("value") or 0) + float(((it.get("shippingOptions") or [{}])[0].get("shippingCost") or {}).get("value") or 0)
            if p > 0:
                ps.append(p)
        med = round(statistics.median(ps), 2) if ps else 0
        ok = len(ps) >= 3 and 60 <= med <= 1000
        res.append({"型番": md, "新品の件数": len(ps), "中央値": med, "結果": "足す" if ok else "足さない"})
        if ok:
            out.append({"maker": mk, "model": md, "n": len(ps), "med": med, "cond": "新品", "足した日時": jst(),
                        "なぜ": "新品の試し（11/21 オーナー「はい、やります」）・eBay 新品 %d件・中央値 $%.0f" % (len(ps), med)})
    out.sort(key=lambda a: -a["n"])
    out = out[:cap]
    if out:
        save_json(add_p, add + out)
    save_json(os.path.join(ROOT, "data", "型番リスト", "新品の試し.json"), {"時刻": jst(), "足した": [a["model"] for a in out], "全部": res})
    print("候補", len(CANDS), "／足した", len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

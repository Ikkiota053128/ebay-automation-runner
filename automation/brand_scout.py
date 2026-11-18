"""知らないブランドの候補（教科書 第3章「キーワードリストは育つもの」の②）

- 種：フリマ新着の地引網で「型番リストにない」品の名前（data/型番リスト/リストにない品/日付.json・直近30日）。
- 名前の頭の英字のブランドを数え、型番リストにあるメーカー・決めごとA（キャラクター・ゲーム）・規約のリスクの言葉を外す。
- eBay に実際に出品があるか（Browse の検索件数。eBay の画面は開かない）を確かめ、件数が「最低の出品数」以上のものだけ候補。
- 候補は月1回（毎月1日）まとめて知らせる：data/型番リスト/ブランドの候補.json。オーナーが OK を出したブランドは、
  Claude が「状態」を "OK" にする → このプログラムが毎日、そのブランドの型番を eBay から集め（3件以上・中央値 $70 以上）、
  data/型番リスト/追加.json に足す（店・フリマの地引網が探すようになる）。
"""
import collections, os, re, sys, glob, statistics, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, jst, now, notify, load_json, save_json, timetable, write_run, mark_started, browse_stopped, num
from flea_sweep import gas_get_models
from price_adjust import JUNK, BOOK, REF_ACC, ACC, model_of
from model_grow import mkey, size_code, BIG, ADD_P
import judge

NAME = "知らないブランドの候補"
CAND_P = os.path.join(ROOT, "data", "型番リスト", "ブランドの候補.json")
STOP = re.compile(r"^(the|new|used|japan|jp|vintage|rare|mint|near|exc|excellent|junk|set|lot|for|with|and|of|in|a|w|f|no|box|item|free|"
                  r"camera|lens|watch|guitar|bass|pedal|effect|effector|digital|film|auto|af|mf|mm|cm|ml|g|kg|x|v|ver|type|model|color|black|white|silver|gold|"
                  r"red|blue|green|pink|brown|gray|grey|navy|beige|size|s|m|l|xl|sale|ok|good|very|nice|working|tested|untested|parts|only|body|kit)$", re.I)


def brands_in(title):
    t = re.sub(r"[【\[（(].*?[】\]）)]", " ", str(title))
    w = re.findall(r"[A-Za-z][A-Za-z0-9&'.-]{2,}", t)
    return [x.strip(".-'") for x in w[:1] if not STOP.match(x) and not re.search(r"\d", x)]


def ebay_total(eb, q):
    p = "/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode({"q": q, "limit": 1, "filter": "buyingOptions:{FIXED_PRICE}"})
    _, j = eb.call("GET", p, kind="app", headers={"X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
    return int(j.get("total") or 0)


def seed_models(eb, brand, have, min_med):
    """OK のブランドの型番を eBay（即決・中古）から集める"""
    items = eb.browse(brand, "buyingOptions:{FIXED_PRICE},conditionIds:{3000|4000|5000|6000}", limit=200)
    rx = re.compile(r"(^|[^A-Za-z])" + re.escape(brand) + r"([^A-Za-z]|$)", re.I)
    by = {}
    for it in items:
        t = str(it.get("title", ""))
        if not rx.search(t) or JUNK.search(t) or BOOK.search(t) or REF_ACC.search(t) or ACC.search(t) or judge.RULE_OUT.search(t):
            continue
        md = model_of(t)
        if not md or len(mkey(md)) < 4 or not re.search(r"\d", md) or size_code(brand, md) or BIG.search(t):
            continue
        by.setdefault(mkey(md), {"md": md, "ps": [], "t": t})["ps"].append(num((it.get("price") or {}).get("value")) or 0)
    out = []
    for k, v in by.items():
        ps = sorted(p for p in v["ps"] if p > 0)
        if len(ps) >= 3 and k not in have and statistics.median(ps) >= min_med:
            out.append({"maker": brand, "model": v["md"], "n": len(ps), "med": round(statistics.median(ps), 2), "例": v["t"][:80], "cond": "中古",
                        "足した日時": jst(), "なぜ": "OK のブランド（%s）・eBay %d件・中央値 $%.0f" % (brand, len(ps), statistics.median(ps))})
    return sorted(out, key=lambda c: -c["n"])


def main():
    tt = timetable(NAME)
    mark_started(NAME)
    eb = Ebay()
    if not eb.ready() or browse_stopped():
        write_run(NAME, True, 0, 0)
        return 0
    cand = load_json(CAND_P, {})
    gas = gas_get_models() or {"models": []}
    add = load_json(ADD_P, [])
    have = {mkey(m.get("model")) for m in gas["models"]} | {mkey(a["model"]) for a in add}
    known = {str(m.get("maker", "")).lower() for m in gas["models"]} | {str(a.get("maker", "")).lower() for a in add}
    msg = []
    # 1) OK のブランド → 型番を足す（毎日・まだ足していないものだけ）
    added = []
    for b, v in cand.items():
        if v.get("状態") == "OK" and not v.get("型番を足した日時"):
            new = seed_models(eb, b, have, float(tt.get("最低の中央値_ドル", 70)))[: int(tt.get("1ブランドに足す上限_件", 15))]
            add += new
            have |= {mkey(n["model"]) for n in new}
            v["型番を足した日時"], v["足した型番"] = jst(), [n["model"] for n in new]
            added.append("%s %d個" % (b, len(new)))
    if added:
        save_json(ADD_P, add)
        msg.append("OK のブランドの型番を型番リストに足した：" + "・".join(added))
    # 2) 候補を探す（毎月1日。手で動かしたときも）
    if now().day == 1 or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        cnt = collections.Counter()
        cutoff = (now().timestamp() - 30 * 86400)
        for f in glob.glob(os.path.join(ROOT, "data", "型番リスト", "リストにない品", "*.json")):
            if os.path.getmtime(f) < cutoff:
                continue
            for t in load_json(f, []):
                if judge.RULE_OUT.search(str(t)):
                    continue
                for b in set(brands_in(t)):
                    cnt[b.lower()] += 1
        todo = [(b, n) for b, n in cnt.most_common() if n >= int(tt.get("最低の回数", 3)) and b not in known and b not in cand][: int(tt.get("1回に確かめる上限", 40))]
        new = []
        for b, n in todo:
            try:
                tot = ebay_total(eb, b)
            except Exception:
                continue
            if tot >= int(tt.get("最低の出品数", 200)):
                cand[b] = {"状態": "候補", "フリマで見た回数_30日": n, "eBayの即決の出品数": tot, "見つけた日時": jst()}
                new.append("%s（フリマ %d回・eBay %s件）" % (b, n, format(tot, ",")))
            else:
                cand[b] = {"状態": "外した", "フリマで見た回数_30日": n, "eBayの即決の出品数": tot, "見つけた日時": jst()}
        msg.append("【知らないブランドの候補】%s：%d個%s" % (jst()[:10], len(new), ("\n" + "\n".join(new[:30]) + "\n→ 出したいブランドを Claude に「○○ OK」と伝えてください") if new else ""))
    save_json(CAND_P, cand)
    if msg:
        print("\n".join(msg))
        notify("\n".join(msg))
    write_run(NAME, True, len(added), 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())

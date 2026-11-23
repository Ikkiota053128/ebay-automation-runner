"""GAS へ回している品のカテゴリを、eBay のカテゴリの API で調べるだけ（eBay は変えない）。
11/23 18:54 オーナー「1を調べて」。判定の記録（今日）で「決めてある種類のカテゴリではない」になった品のカテゴリ番号を数え、
多い順に、カテゴリの名前（上の階層つき）・必ず入れる項目（Required）・よく使う項目・その品の例（仕入れ先の商品名）を出す。
結果は data/判定/カテゴリの下調べ.json。"""
import collections, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json

eb = Ebay()
cnt, ex = collections.Counter(), collections.defaultdict(list)
for f in glob.glob(os.path.join(ROOT, "data", "判定", "記録", "2026112*_*.json")):
    for r in json.load(open(f, encoding="utf-8")).get("結果", []):
        m = re.search(r"決めてある種類のカテゴリではない（(\d+)）", r.get("理由", ""))
        if m and r.get("id") not in {x[0] for x in ex[m.group(1)]}:
            cnt[m.group(1)] += 1
            if len(ex[m.group(1)]) < 6:
                ex[m.group(1)].append((r.get("id"), r.get("商品名") or r.get("タイトル") or r.get("型番")))
out = {"時刻": jst(), "カテゴリ": []}
for cid, n in cnt.most_common(25):
    d = {"番号": cid, "品の数": n, "例": [e[1] for e in ex[cid]]}
    try:
        _, s = eb.call("GET", "/commerce/taxonomy/v1/category_tree/0/get_category_subtree?category_id=" + cid)
        node = (s or {}).get("categorySubtreeNode") or {}
        d["名前"] = (node.get("category") or {}).get("categoryName")
        d["上の階層"] = " > ".join(a.get("categoryName", "") for a in (node.get("parentCategoryTreeNodeHref") and [] or []))
        _, a = eb.call("GET", "/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category?category_id=" + cid)
        asp = (a or {}).get("aspects") or []
        d["必ず入れる項目"] = [x["localizedAspectName"] for x in asp if (x.get("aspectConstraint") or {}).get("aspectRequired")]
        d["よく使う項目"] = [x["localizedAspectName"] for x in asp if (x.get("aspectConstraint") or {}).get("aspectUsage") == "RECOMMENDED"][:12]
    except EbayError as e:
        d["エラー"] = err_text(e)[:200]
    out["カテゴリ"].append(d)
save_json(os.path.join(ROOT, "data", "判定", "カテゴリの下調べ.json"), out)
print(len(out["カテゴリ"]))

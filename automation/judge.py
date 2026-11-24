"""判定（教科書 第5章・GAS v663 の quotePrice_・shipYen_ と同じ式）：店の地引網の候補を、GitHub だけで GO／見送りにする。

- 対象は「前に出品したことのある型番」だけ（data/判定/型番の実績.json）。カテゴリ・項目・重さ・箱・手数料率・関税率は、その実績を使い回す。
- 送料は FedEx（SpeedPAK via FedEx・ゾーンF）の表で計算し直す（data/判定/送料表.json）。
- eBay の相場は Browse（同じ型番・同じ状態・即決・自分を除く・送料込み）。付属品・ジャンク・外れ値は値段の調整と同じ決まりで外す。
- 値段：最安より $1 安く（$100以上は1%）→ 無理ならフロア（2番目＋許容幅以内／相場の真ん中以内／相場の1.4倍以内）。
  11/21 オーナー「教科書通りやって」：店の設定の high・tol・textbook で、いつも最安−$1、フロアは2番目＋10%以内だけ（教科書 第5章）。
- 利益の条件：利益額1,500円 かつ 利益率5%（設定 F123 がオフ＝両方）。
- いまは「影の運転」：答えを data/判定/影/ に書くだけ。GAS の答えと並べて比べる。
"""
import collections, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, load_json, num
from price_adjust import JUNK, is_acc, clean, norm

RULE_OUT = re.compile(r"pokemon|pokémon|nintendo|switch|playstation|\bps[2-5]\b|game|anime|figure|sanrio|disney|gundam|"
                      r"limited|collab|japan only|card|ポケモン|任天堂|限定|コラボ|フィギュア|ゲーム|プレステ|プレイステーション|ニンテンドー|スイッチ", re.I)
# 付属品・部品（本体ではない）：「型番用」「バンド」「ベルト」など（店の商品名で多い）
ACC_JA = re.compile(r"用(?![意途])|対応|互換|交換|替え|バンド|ベルト|ストラップ|ベゼル|風防|裏蓋|ケースのみ|ケース単品|箱のみ|空箱|保護フィルム|"
                    r"フィルム(?!カメラ)|カバー|充電器|充電ケーブル|ケーブル|アダプター|アダプタ|バッテリー|電池パック|リモコン|説明書のみ|"
                    r"部品|パーツ|ジャンク|修理|レンズキャップ|フード|ボディキャップ|コントローラー(?!付)|バッグ|カメラケース|ケース")
PROMO = re.compile(r"【[^】]*】|\[[^\]]*\]|＼[^／]*／")


def plain(t):
    """店の宣伝（【11/18限定！…】など）を外した商品名"""
    return PROMO.sub(" ", str(t or ""))


def is_acc_ja(t, model):
    t = plain(t)
    k = re.sub(r"[^A-Z0-9]", "", str(model).upper())
    if re.search(re.escape(str(model)) + r"\s*(用|対応)", t, re.I) or (k and re.search(k + r"用", re.sub(r"[-\s]", "", t.upper()))):
        return True
    if len(set(re.findall(r"\b[A-Z]{1,5}-?\d{2,5}[A-Z0-9-]*", t.upper()))) >= 4:   # 型番がたくさん並ぶ＝「〜に対応」の付属品
        return True
    # 「レンズキャップ付」「アダプター・ケーブル付」「BOX付属」のような付いてくる物の言葉は、付属品の印にしない（11/19 オーナー「付属品の見分けを見直す」）
    t2 = re.sub(r"[^\s　、，,/]{0,14}(付き|付属|付|同梱|あり|有り)(?![けい])", " ", t)
    t2 = re.sub(r"使用|実用|業務用|兼用|(ギター|ベース|キーボード|ボーカル|アコギ|エレキ|メンズ|レディース|男性|女性|子供|キッズ|プロ|家庭)用|フジフィルム|富士フイルム|富士フィルム", " ", t2)
    if not ACC_JA.search(t2):
        return False
    body = re.search(r"本体|ボディ(?!キャップ)|一式|腕時計|デジタルカメラ|フィルムカメラ|コンパクトカメラ|一眼レフ|ミラーレス|エフェクター|コンプレッサー|"
                     r"オーバードライブ|ディストーション|自動巻|ダイバーズ|ダイバー|ソーラー|エコ・?ドライブ|電波|機械式|クオーツ|クォーツ", t2)
    strong = re.search(r"用(?![意途])|対応|互換|交換|専用|替え|保護フィルム|フィルム(?!カメラ)|のみ|単品|純正.{0,12}(ベルト|バンド|ブレス)|(ベルト|バンド|ブレス).{0,8}純正|"
                       r"(ステンレス|メタル|ウレタン|ラバー|レザー|ナイロン|ナトー)\s*(ベルト|バンド|ブレス)|時計ベルト|時計バンド|充電器|バッテリー|電池パック|ジャンク|部品|パーツ|修理|ハンドル|バッグ|カメラケース", t2)
    return not (body and not strong)


NEW_JA = re.compile(r"新品|未開封|未使用品?(?!に近い)|国内正規品|正規品|メーカー保証|保証書付|メーカー1年保証|当店保証1年|在庫あり|即納")
USED_JA = re.compile(r"中古|ユーズド|USED|used|美品|良品|ジャンク|難あり|訳あり|開封品|展示品|アウトレット|未使用に近い")


def mkey(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def same_model(a, b):
    if not a or not b:
        return False
    s, l = sorted((a, b), key=len)
    return len(s) >= 5 and l.startswith(s)


def materials():
    d = os.path.join(ROOT, "data", "判定")
    return load_json(os.path.join(d, "型番の実績.json"), {}), load_json(os.path.join(d, "送料表.json"), {})


def profile_for(model, profs):
    k = mkey(model)
    if k in profs:
        return profs[k]
    hits = [v for kk, v in profs.items() if same_model(k, kk)]
    return max(hits, key=lambda v: v.get("順", 0)) if len(hits) == 1 else None   # 2つ以上当たるときは型番があいまい → 使わない


def box3(t):
    n = sorted([float(x) for x in re.split(r"[x×*\s]+", str(t or "")) if x and re.match(r"^[\d.]+$", x) and float(x) > 0], reverse=True)
    return n if len(n) == 3 else [0, 0, 0]


def ship_fedex(w, box, tbl):
    """GAS shipYen_ の FedEx と同じ：請求重量=max(実重量, 縦×横×高さ/5)、割増=ceil(max(実重量,容積/8)/500)×割増、燃油を掛ける"""
    l, wd, h = box3(box)
    vol = l * wd * h
    if l and (l > 274 or l + 2 * wd + 2 * h > 330):
        return None
    ww = max(w, math.ceil(vol / 5))
    key = math.ceil(ww / 500) * 500 if ww <= 20000 else math.ceil(ww / 1000) * 1000
    hit = next((y for k, y in tbl["表_ゾーンF"] if k >= key), None)
    if hit is None:
        return None
    ap = max(w, vol / 8)
    extra = math.ceil(math.floor(ap * 10) / 10 / 500) * tbl["割増_500gごと"]
    return round((hit + extra) * (1 + tbl["燃油"]))


def cond_of(title_ja):
    t = str(title_ja or "")
    if re.search(r"新品同様|新品仕上|新品に近い|新品級|未使用に近い|展示品|開封済|中古", t):
        return 3000
    if USED_JA.search(t):
        return 3000
    if NEW_JA.search(t):
        return 1000
    return None


CAT_NAMES = {}   # eBay のカテゴリ番号 → 名前（競合の出品から）


_CC = {"path": None, "d": {}, "ttl": 0, "hit": 0, "miss": 0}


def comp_cache_load(path, hours, none_hours=None):
    """相場（競合の値段）の使い回し：同じ型番・同じ状態・同じカテゴリの結果を hours 時間使う。
    競合が見つからなかった結果は none_hours 時間使う（11/19 10:32 オーナー「使い回し3日をやって」：GASと同じ 3日・競合なし7日）"""
    import json as _j, os as _o, time as _t
    _CC.update(path=path, ttl=float(hours) * 3600, ttl_none=float(none_hours if none_hours is not None else hours) * 3600, hit=0, miss=0)
    try:
        d = _j.load(open(path, encoding="utf-8")) if _o.path.exists(path) else {}
    except Exception:
        d = {}
    now_ = _t.time()
    _CC["d"] = {k: v for k, v in d.items() if v.get("t", 0) >= now_ - (_CC["ttl"] if v.get("p") else _CC["ttl_none"])}


def comp_cache_save():
    import json as _j, os as _o
    if _CC["path"]:
        _o.makedirs(_o.path.dirname(_CC["path"]), exist_ok=True)
        _j.dump(_CC["d"], open(_CC["path"], "w", encoding="utf-8"), ensure_ascii=False)
    return _CC["hit"], _CC["miss"]


def comps(eb, model, cond, me, my_ids, cats=None, cat=None):
    import time as _t
    k = "%s|%s|%s" % (norm(model), "used" if cond >= 3000 else "new", cat or "")
    if _CC["ttl"] and k in _CC["d"]:
        _CC["hit"] += 1
        v = _CC["d"][k]
        if cats is not None:
            cats.extend(v.get("c", []))
        return list(v["p"])
    cc = []
    ps = _comps(eb, model, cond, me, my_ids, cc, cat)
    if cats is not None:
        cats.extend(cc)
    if _CC["ttl"]:
        _CC["miss"] += 1
        _CC["d"][k] = {"t": _t.time(), "p": ps, "c": cc}
    return ps


def _comps(eb, model, cond, me, my_ids, cats=None, cat=None):
    """同じ型番・同じ状態・即決・送料込み（米国の買い手に見える送料）。値段の調整と同じ外し方。返事：送料込みの値段（安い順）
    cats にリストを渡すと、残った競合の一番下のカテゴリ（leafCategoryIds）を入れる"""
    filt = "buyingOptions:{FIXED_PRICE},conditionIds:{%s}" % ("1000|1500" if cond < 3000 else "3000|4000|5000|6000")
    items = eb.browse(model, filt, category=cat) if cat else eb.browse(model, filt)
    md = norm(model)
    out = []
    for it in items:
        if (it.get("seller") or {}).get("username", "").lower() == me or str(it.get("legacyItemId", "")) in my_ids:
            continue
        t = it.get("title", "")
        if md not in norm(t) or JUNK.search(t) or is_acc(t, model):
            continue
        p = num((it.get("price") or {}).get("value"))
        if not p or (it.get("price") or {}).get("currency", "USD") != "USD":
            continue
        so = it.get("shippingOptions") or []
        sh = num(so[0]["shippingCost"].get("value")) if so and so[0].get("shippingCost") else 0.0
        for cc in it.get("categories") or []:
            if cc.get("categoryId") and cc.get("categoryName"):
                CAT_NAMES.setdefault(str(cc["categoryId"]), cc["categoryName"])
        out.append({"p": round(p + (sh or 0), 2), "t": t, "c": str((it.get("leafCategoryIds") or [""])[0])})
    kept = clean(out)
    if kept and not cat:
        # 型番で探すと、付属品（フィルム・電池・ノブなど）が本体より多く出ることがある。本体は高いので、
        # 値段の高いほうから1割（3件以上）の出品で一番多いカテゴリを「本体のカテゴリ」とし、そのカテゴリの出品だけを競合にする
        top = sorted(kept, key=lambda x: -x["p"])[: max(3, len(kept) // 10)]
        upper = [x["c"] for x in top if x["c"]]
        if upper:
            main = collections.Counter(upper).most_common(1)[0][0]
            kept = [x for x in kept if x["c"] == main] or kept
    if cats is not None:
        cats.extend(x["c"] for x in kept if x["c"])
    return sorted(x["p"] for x in kept)


def floor_price(base, keep, fx, fl_yen, fl_rate):
    """GAS floorPriceFor_（両方を満たす）：max((base+1500)/keep/fx, base/(keep-5%)/fx) をセント単位で切り上げ"""
    if keep <= 0 or fx <= 0:
        return None
    a = (base + fl_yen) / keep / fx
    b = base / (keep - fl_rate) / fx if keep - fl_rate > 0 else float("inf")
    v = max(a, b)
    return math.ceil(v * 100 - 1e-6) / 100 if math.isfinite(v) else None


def quote(act0, d, qs):
    """GAS quotePrice_ の②（Active の競合がある場合）。競合が無い品は見送り（GAS の③④は使わない＝相場と比べられない品は出さない）"""
    r2 = lambda x: round(x * 100) / 100
    k = d["fee"] + d["duty"]
    base = d["cost"] + d["dom"] + d["ship"] + d["fixed"]
    fp = floor_price(base, 1 - k, d["fx"], qs["floorYen"], qs["floorRate"])
    if fp is None:
        return None, "利益の計算ができない", fp
    act0 = sorted(x for x in act0 if x > 0)
    if not act0:
        return None, "eBayに同じ型番の競合が無い（相場と比べられない）", fp
    mid = act0[(len(act0) - 1) // 2] if len(act0) >= 3 else 0
    act = [x for x in act0 if x >= mid * 0.5] if mid > 0 else act0[:]
    top = act0[len(act0) // 2:]
    um = top[(len(top) - 1) // 2] if top else 0
    med = act0[len(act0) // 2]
    ref = max(um, med)
    if ref > 0 and act:
        f = [x for x in act if x >= ref * 0.35]
        act = f or [med]
    if len(act0) >= 5:
        f = [x for x in act if x >= med * 0.65]
        act = f or [med]
        dr = 0
        while len(act) >= 3 and dr < 2 and act[0] < act[1] * 0.85 and act[0] < med * 0.7:
            act, dr = act[1:], dr + 1
    L = act[0]
    L2 = act[1] if len(act) >= 2 else 0
    target = r2(L * 0.99 if L >= qs["high"] else L - 1)
    if target >= fp:
        return target, "最安 $%.2f より%s安く" % (L, "1%" if L >= qs["high"] else "$1"), fp
    if qs.get("strict2"):   # 11/23 14:08 オーナー「最安値か最安値から2番目の商品しか出さないで」：フロアが2番目より安いときだけ（2番目の位置）
        if L2 and fp < L2:
            return fp, "フロア（最安 $%.2f の次・2番目 $%.2f より安い）" % (L, L2), fp
        return None, "見送り：フロア $%.2f では最安か2番目に入れない（%s）" % (fp, ("2番目 $%.2f" % L2) if L2 else "最安 $%.2f・2番目なし" % L), fp
    if L2 and fp <= L2 * (1 + qs["tol"]):
        return fp, "フロア（2番目 $%.2f ＋%d%%以内）" % (L2, round(qs["tol"] * 100)), fp
    if qs.get("textbook"):   # 11/21 12:35 オーナー「教科書通りやって」：フロアは2番目＋許容幅（教科書 10%）の中だけ。相場の真ん中・1.4倍の線は使わない
        return None, "見送り：フロア $%.2f が%s（教科書）" % (fp, ("2番目 $%.2f の＋%d%%を超える" % (L2, round(qs["tol"] * 100))) if L2 else "最安 $%.2f より高く、2番目の競合が無い" % L), fp
    if len(act0) >= 5 and fp <= med:
        return fp, "フロア（相場の真ん中 $%.2f 以内）" % med, fp
    ref = max(med, L2 or 0, L)
    if fp <= ref * qs["overMax"]:
        return fp, "フロア（競合より高い・相場 $%.2f の%d%%）" % (ref, round(fp / ref * 100)), fp
    return None, "見送り：フロア $%.2f が相場 $%.2f の%.1f倍を超える" % (fp, ref, qs["overMax"]), fp


def cost_plus(d, qs, cfg):
    """教科書 第5章のコストプラス（競合が無い品）：利益＝売値の 15%（コストプラス_売値に対する利益率）、1品の利益は 2万円まで（コストプラス_1品の利益の上限_円）。
    フロア（5%・1,500円）より安くはしない。11/24 19:23 オーナー「おすすめは 2でお願いします」"""
    k = d["fee"] + d["duty"]
    base = d["cost"] + d["dom"] + d["ship"] + d["fixed"]
    fp = floor_price(base, 1 - k, d["fx"], qs["floorYen"], qs["floorRate"])
    rate = float(cfg.get("コストプラス_売値に対する利益率", 0.15))
    cap = float(cfg.get("コストプラス_1品の利益の上限_円", 20000))
    if fp is None or 1 - k - rate <= 0:
        return None, "利益の計算ができない", fp
    p = base / (d["fx"] * (1 - k - rate))
    if p * d["fx"] * rate > cap:
        p = (base + cap) / (d["fx"] * (1 - k))
    p = max(p, fp)
    p = math.ceil(p * 100 - 1e-6) / 100
    return p, "コストプラス（競合なし・利益は売値の%d%%・上限%d円）" % (round(rate * 100), cap), fp


def profit(price, d):
    raw = price * d["fx"] * (1 - d["fee"] - d["duty"]) - d["cost"] - d["dom"] - d["ship"] - d["fixed"]
    return round(raw), raw / (price * d["fx"]) if price else 0


def judge(eb, cand, profs, ship_tbl, qs, me, my_ids, fx):
    """1品を判定。返事：{"結論": "GO"/"見送り", "理由", ...}"""
    r = {"url": cand["url"], "型番": cand["型番"], "仕入値": cand["price"], "タイトル（仕入元）": cand["title"][:80]}
    if RULE_OUT.search(cand["title"]):
        return dict(r, 結論="見送り", 理由="キャラクター・ゲーム・限定品（決めごとA）")
    pf = profile_for(cand["型番"], profs)
    if not pf:
        return dict(r, 結論="対象外", 理由="出品したことのない型番（GASが判定）")
    cond = cond_of(cand["title"])
    if cond is None:
        return dict(r, 結論="見送り", 理由="新品か中古か商品名から読めない")
    ship = ship_fedex(pf["重さ_g"], pf["箱"], ship_tbl["FedEx"])
    if not ship:
        return dict(r, 結論="見送り", 理由="FedExで送れない大きさ")
    d = {"cost": cand["price"], "dom": cand.get("dom", 2000), "ship": ship, "fee": pf["手数料率"] or 0.1742,
         "duty": pf["関税率"] if pf["関税率"] is not None else 0.15, "fixed": pf["固定費"] or 0, "fx": fx}
    act = comps(eb, pf["型番"], cond, me, my_ids)
    price, how, fp = quote(act, d, qs)
    r.update({"実績の出品ID": pf["出品ID"], "カテゴリ": pf["カテゴリ"], "状態ID": cond, "送料": ship, "国内送料": d["dom"],
              "フロア": fp, "競合": act[:5], "競合の数": len(act), "値段の決め方": how})
    if price is None:
        return dict(r, 結論="見送り", 理由=how)
    py, pr = profit(price, d)
    ok = py >= qs["floorYen"] and pr >= qs["floorRate"] - 1e-9
    r.update({"値段": price, "利益": py, "利益率": round(pr, 4)})
    return dict(r, 結論="GO" if ok else "見送り", 理由="" if ok else "利益の条件を満たさない")

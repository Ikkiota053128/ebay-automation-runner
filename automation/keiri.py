"""店の経理（11/25 09:25 オーナー「店の経理を任せたい」①〜⑤）。
使い方：
  python3 keiri.py record              … ① 注文ごとの見積を 経理の注文台帳 に記録（受注の通知のあとに毎回）
  python3 keiri.py import CSV YYYYMM   … ② eBay の取引レポートCSV を、買い手の欄を落として data/経理/明細/YYYYMM.csv に入れる
  python3 keiri.py close YYYYMM        … ②〜⑤ 月次締め：見積を実額に置き換え、利益を確定し、凍結して、月次レポートを作る
決まり（設計書4章）：
- 注文の記録（data/注文の記録/）と明細の買い手の欄は、このプログラムの中だけで読む。経理の台帳・レポートには、注文番号・買い手の名前・住所を書かない
  （注文は 注文キー＝注文番号のハッシュ だけ）。AI に見せるのは件数・SKU・金額だけ。
- 締めた月（data/経理/締め/YYYYMM.json の 凍結 true）の行は、もう変えない。
- 消費税の還付は見込み（申告は税理士に相談）。"""
import csv, datetime as dt, glob, hashlib, io, json, os, re, sys
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, load_json, save_json, read_ledger, settings, num, notify

PT = ZoneInfo("America/Los_Angeles")
D = os.path.join(ROOT, "data", "経理")
BOOK = os.path.join(D, "注文台帳.csv")
COLS = ["明細キー", "注文キー", "注文日_PT", "月_PT", "SKU", "タイトル", "仕入元の種類", "仕入先の区分",
        "売上_ドル", "為替_見積", "売上_円_見積", "仕入値_円", "仕入値の出どころ", "仕入れた日", "国内送料_円", "固定費_円",
        "海外送料_円_見積", "手数料_円_見積", "関税_円_見積", "利益_円_見積",
        "売上_円_実額", "手数料_円_実額", "広告_円_実額", "送料_円_実額", "返金_円_実額", "その他_円_実額", "利益_円_実額",
        "状態", "締め月"]
# 仕入れ先の区分（消費税の見込みのため）：事業者（インボイスがあるとみなす）／個人（フリマ・オークション）
PERSON = re.compile(r"paypayfleamarket|auctions\.yahoo|mercari|fril\.jp", re.I)


def h(s):
    return hashlib.sha256(str(s).encode()).hexdigest()[:24]


def f2(x):
    return "" if x is None or x == "" else ("%.0f" % float(x))


def read_book():
    if not os.path.exists(BOOK):
        return []
    with open(BOOK, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_book(rows):
    os.makedirs(D, exist_ok=True)
    tmp = BOOK + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, BOOK)


def frozen(ym):
    return bool(load_json(os.path.join(D, "締め", ym + ".json"), {}).get("凍結"))


def kobutsu_costs():
    """古物台帳（「SKU 仕入れた ○円」の答え）から SKU → (仕入値, 日)。同じ SKU は新しい方"""
    out = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, "data", "古物台帳", "*.csv"))):
        with open(fp, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                v = num(r.get("代価(円)"))
                if r.get("SKU") and v:
                    out[r["SKU"]] = (v, r.get("取引の日", ""))
    return out


def estimate(row, led, cfg, kb):
    """見積の欄を埋める（締めていない行だけ）"""
    f = cfg.get("値付けの式_第5章", {})
    r = led.get(row["SKU"], {})
    fx = num(r.get("為替")) or f.get("為替_円per米ドル", 150)
    usd = num(row["売上_ドル"]) or 0
    fee = num(str(r.get("手数料率", "")).replace("%", ""))
    fee = (fee / 100 if fee and fee > 1 else fee) if fee is not None else f.get("eBay手数料_売値に対する割合", 0.15) + f.get("広告_売値に対する割合", 0)
    duty = num(str(r.get("関税率", "")).replace("%", ""))
    duty = (duty / 100 if duty and duty > 1 else duty) if duty is not None else f.get("米国関税_売値に対する割合", 0.15)
    if row["SKU"] in kb:
        cost, day, src = kb[row["SKU"]][0], kb[row["SKU"]][1], "仕入れた（答え）"
    else:
        cost, day, src = num(r.get("仕入値(円)")), "", "出品時の仕入値（見積）"
    row.update({"タイトル": (r.get("タイトル") or row.get("タイトル") or "")[:80], "仕入元の種類": r.get("仕入元の種類", ""),
                "仕入先の区分": "個人" if PERSON.search(r.get("仕入元URL") or "") else ("事業者" if r.get("仕入元URL") else "不明"),
                "為替_見積": "%.2f" % fx, "売上_円_見積": f2(usd * fx), "仕入値_円": f2(cost), "仕入値の出どころ": src if cost else "不明",
                "仕入れた日": day, "国内送料_円": f2(num(r.get("国内送料(円)")) or 0), "固定費_円": f2(num(r.get("固定費(円)")) or 0),
                "海外送料_円_見積": f2(num(r.get("出品時の海外送料(円)"))), "手数料_円_見積": f2(usd * fx * fee), "関税_円_見積": f2(usd * fx * duty)})
    parts = [num(row[k]) for k in ("仕入値_円", "国内送料_円", "固定費_円", "海外送料_円_見積", "手数料_円_見積", "関税_円_見積")]
    row["利益_円_見積"] = f2(usd * fx - sum(p or 0 for p in parts)) if cost else ""
    return row


def record():
    """① 注文の記録から、経理の注文台帳に見積の行を足す（注文番号は台帳に書かない）"""
    cfg, led, kb = settings(), {r["SKU"]: r for r in read_ledger()}, kobutsu_costs()
    rows = read_book()
    have = {r["明細キー"]: r for r in rows}
    added = 0
    for fp in sorted(glob.glob(os.path.join(ROOT, "data", "注文の記録", "*.json"))):
        o = load_json(fp, {})
        key = os.path.basename(fp).split("_", 1)[-1].rsplit(".", 1)[0]
        if not o.get("SKU"):
            continue
        t = o.get("注文の時刻_UTC") or ""
        try:
            pt = dt.datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).astimezone(PT)
        except ValueError:
            pt = dt.datetime.now(PT)
        if key not in have:
            row = {c: "" for c in COLS}
            row.update({"明細キー": key, "注文キー": h(o.get("注文番号", "")), "注文日_PT": pt.strftime("%Y-%m-%d"), "月_PT": pt.strftime("%Y%m"),
                        "SKU": o["SKU"], "売上_ドル": "%.2f" % (num(o.get("売値")) or 0), "状態": "見積"})
            rows.append(row)
            have[key] = row
            added += 1
        row = have[key]
        if row.get("締め月") or frozen(row["月_PT"]):
            continue
        estimate(row, led, cfg, kb)
    rows.sort(key=lambda r: (r["注文日_PT"], r["明細キー"]))
    write_book(rows)
    print("経理の注文台帳：%d行（新しく %d行）" % (len(rows), added))
    return 0


# ---- ② 明細の取り込み（買い手の欄は落とす） ----
KEEP = {  # 残す欄：名前に入っている言葉（英語・日本語）→ 中の名前
    "日": [r"transaction creation date", r"取引.*作成日", r"^date$", r"日付"],
    "種類": [r"^type$", r"^タイプ$", r"取引の種類", r"種類"],
    "注文番号": [r"^order number$", r"注文番号"],
    "出品ID": [r"^item id$", r"商品番号", r"出品番号"],
    "SKU": [r"custom label", r"カスタムラベル", r"^sku$"],
    "小計": [r"item subtotal", r"商品の小計", r"小計"],
    "送料受取": [r"shipping and handling", r"送料および手数料", r"配送料"],
    "総額": [r"gross transaction amount", r"取引総額"],
    "手数料_固定": [r"final value fee.*fixed", r"落札手数料.*固定", r"販売手数料.*固定"],
    "手数料_変動": [r"final value fee.*variable", r"落札手数料.*変動", r"販売手数料.*変動"],
    "海外手数料": [r"international fee", r"海外.*手数料"],
    "その他手数料": [r"not as described fee", r"below standard", r"規定.*手数料"],
    "純額": [r"^net amount$", r"純額", r"正味"],
    "通貨": [r"payout currency", r"transaction currency", r"通貨"],
    "為替": [r"exchange rate", r"為替"],
    "説明": [r"^description$", r"説明"],
}


def find_header(lines):
    for i, ln in enumerate(lines[:60]):
        low = ln.lower()
        if ("type" in low or "タイプ" in ln or "種類" in ln) and ("order number" in low or "注文番号" in ln):
            return i
    return None


def do_import(path, ym):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp932", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.splitlines()
    hi = find_header(lines)
    if hi is None:
        print("見出しの行が見つからない（Type と Order number の欄）")
        return 1
    rd = csv.reader(io.StringIO("\n".join(lines[hi:])))
    head = next(rd)
    idx = {}
    for name, pats in KEEP.items():
        for j, col in enumerate(head):
            if any(re.search(p, col.strip(), re.I) for p in pats) and j not in idx.values():
                idx[name] = j
                break
    print("欄の名前（中身は出さない）：", " | ".join(c.strip() for c in head))
    print("使う欄：", ", ".join("%s←%s" % (k, head[v].strip()) for k, v in idx.items()))
    print("見つからない欄：", ", ".join(k for k in KEEP if k not in idx) or "なし")
    out = []
    for rec in rd:
        if not any(x.strip() for x in rec):
            continue
        g = lambda k: rec[idx[k]].strip() if k in idx and idx[k] < len(rec) else ""
        on = g("注文番号")
        out.append({"日": g("日"), "種類": g("種類"), "注文キー": h(on) if on and on != "--" else "", "出品ID": g("出品ID"), "SKU": g("SKU"),
                    "小計": g("小計"), "送料受取": g("送料受取"), "総額": g("総額"), "手数料_固定": g("手数料_固定"), "手数料_変動": g("手数料_変動"),
                    "海外手数料": g("海外手数料"), "その他手数料": g("その他手数料"), "純額": g("純額"), "通貨": g("通貨"), "為替": g("為替"),
                    "説明": re.sub(r"\S+@\S+", "", g("説明"))[:80]})
    os.makedirs(os.path.join(D, "明細"), exist_ok=True)
    op = os.path.join(D, "明細", ym + ".csv")
    with open(op, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["日"])
        w.writeheader()
        w.writerows(out)
    import collections
    print("取り込んだ行：%d（種類ごと %s）→ %s" % (len(out), dict(collections.Counter(r["種類"] for r in out)), os.path.relpath(op, ROOT)))
    return 0


# ---- ②〜⑤ 月次締め ----
def yen(v, cur, rate, fx):
    """明細の金額を円に（通貨が USD なら明細の為替、無ければ月の見積の為替）"""
    x = num(v)
    if x is None:
        return 0.0
    if (cur or "").upper() in ("USD", "US$", "$", "米ドル"):
        return x * (num(rate) or fx)
    return x


def tax_rate_person(day):
    """インボイスの無い仕入れ（個人）の経過措置（令和8年度の改正後）：〜2026/9/30 80%・2026/10/1〜2028/9/30 70%"""
    return 0.8 if (day or "") < "2026-10-01" else 0.7


def close(ym):
    if frozen(ym):
        print("%s はもう締めて凍結しています（変えない）" % ym)
        return 1
    mp = os.path.join(D, "明細", ym + ".csv")
    if not os.path.exists(mp):
        print("明細がまだ無い：data/経理/明細/%s.csv（import を先に）" % ym)
        return 1
    record()
    cfg = settings()
    f = cfg.get("値付けの式_第5章", {})
    with open(mp, encoding="utf-8-sig") as fh:
        st = list(csv.DictReader(fh))
    rows = read_book()
    mine = [r for r in rows if r["月_PT"] == ym and not r.get("締め月")]
    fx_m = sum(num(r["為替_見積"]) or 0 for r in mine) / len(mine) if mine else f.get("為替_円per米ドル", 150)
    by_key = {}
    for r in mine:
        by_key.setdefault(r["注文キー"], []).append(r)
    act = {}
    month_cost = {"広告": 0.0, "その他の費用": 0.0}
    unmatched = []
    for s in st:
        t = (s["種類"] or "").lower()
        cur, rate = s.get("通貨"), s.get("為替")
        net = yen(s.get("純額"), cur, rate, fx_m)
        k = s.get("注文キー")
        a = act.setdefault(k, {"売上": 0.0, "手数料": 0.0, "広告": 0.0, "送料": 0.0, "返金": 0.0, "その他": 0.0}) if k else None
        if re.search(r"order|注文", t) and a is not None:
            gross = yen(s.get("総額") or s.get("小計"), cur, rate, fx_m)
            a["売上"] += gross
            if s.get("純額"):
                a["手数料"] += gross - net
            else:
                a["手数料"] += sum(abs(yen(s.get(c), cur, rate, fx_m)) for c in ("手数料_固定", "手数料_変動", "海外手数料", "その他手数料"))
        elif re.search(r"refund|返金", t) and a is not None:
            a["返金"] += abs(net)
        elif re.search(r"shipping label|送料|ラベル", t):
            if a is not None:
                a["送料"] += -net
            else:
                month_cost["その他の費用"] += -net
        elif re.search(r"promot|広告|ad fee", t + " " + (s.get("説明") or "").lower()):
            if a is not None:
                a["広告"] += -net
            else:
                month_cost["広告"] += -net
        elif re.search(r"payout|支払い|振込|transfer", t):
            continue
        elif net:
            if a is not None:
                a["その他"] += -net
            else:
                month_cost["その他の費用"] += -net
    for k in [k for k in act if k and k not in by_key]:
        unmatched.append(k[:6])
    # 実額に置き換える
    for k, lines in by_key.items():
        a = act.get(k)
        if not a:
            continue
        tot = sum(num(r["売上_ドル"]) or 0 for r in lines) or 1
        for r in lines:
            w = (num(r["売上_ドル"]) or 0) / tot
            r["売上_円_実額"] = f2(a["売上"] * w)
            r["手数料_円_実額"] = f2(a["手数料"] * w)
            r["広告_円_実額"] = f2(a["広告"] * w)
            r["送料_円_実額"] = f2(a["送料"] * w) if a["送料"] else r["海外送料_円_見積"]
            r["返金_円_実額"] = f2(a["返金"] * w)
            r["その他_円_実額"] = f2(a["その他"] * w)
            cost = sum(num(r[c]) or 0 for c in ("仕入値_円", "国内送料_円", "固定費_円", "送料_円_実額", "手数料_円_実額", "広告_円_実額", "返金_円_実額", "その他_円_実額"))
            # 関税：米国あての関税は eBay の明細の送料・手数料に入る形が多い。明細に関税の行が無いときは見積を残す
            cost += num(r["関税_円_見積"]) or 0
            r["利益_円_実額"] = f2((num(r["売上_円_実額"]) or 0) - cost)
            r["状態"] = "実額"
    for r in mine:
        r["締め月"] = ym
        if r["状態"] != "実額":
            r["状態"] = "見積のまま（明細に無い）"
    write_book(rows)
    rep = report(ym, mine, month_cost, fx_m, f, unmatched)
    save_json(os.path.join(D, "締め", ym + ".json"), {"凍結": True, "締めた日時": jst(), "件数": len(mine), "月の費用": month_cost,
                                                    "明細の行": len(st), "台帳に無い注文（キーの頭）": unmatched})
    print(rep[:3000])
    return 0


def report(ym, rows, month_cost, fx_m, f, unmatched):
    n = len(rows)
    S = lambda c: sum(num(r.get(c)) or 0 for r in rows)
    sales = sum((num(r["売上_円_実額"]) if r["状態"] == "実額" else num(r["売上_円_見積"])) or 0 for r in rows)
    usd = S("売上_ドル")
    cost_buy, dom, fixed = S("仕入値_円"), S("国内送料_円"), S("固定費_円")
    fee = sum((num(r["手数料_円_実額"]) if r["状態"] == "実額" else num(r["手数料_円_見積"])) or 0 for r in rows)
    ad = S("広告_円_実額") + month_cost["広告"]
    ship = sum((num(r["送料_円_実額"]) if r["状態"] == "実額" else num(r["海外送料_円_見積"])) or 0 for r in rows)
    duty, ref, oth = S("関税_円_見積"), S("返金_円_実額"), S("その他_円_実額") + month_cost["その他の費用"]
    profit = sales - (cost_buy + dom + fixed + fee + ad + ship + duty + ref + oth)
    L = ["# 月次レポート %s年%s月（PT・締めた日時 %s）" % (ym[:4], ym[4:], jst()), "",
         "| 項目 | 値 |", "|---|---|",
         "| 売上 | %s円（$%s） |" % (format(round(sales), ","), format(round(usd, 2), ",")),
         "| 件数 | %d件 |" % n,
         "| 平均単価 | %s円（$%.2f） |" % (format(round(sales / n), ",") if n else 0, usd / n if n else 0),
         "| 最終利益 | %s円 |" % format(round(profit), ","),
         "| 平均利益 | %s円 |" % (format(round(profit / n), ",") if n else 0),
         "| 利益率 | %.1f%% |" % (profit / sales * 100 if sales else 0), "",
         "## 費用の内訳", "", "| 費用 | 円 | 売上に対する割合 |", "|---|---|---|"]
    for k, v in [("仕入", cost_buy), ("国内送料", dom), ("固定費（梱包など）", fixed), ("eBay手数料", fee), ("広告", ad),
                 ("海外送料", ship), ("関税（見積）", duty), ("返金", ref), ("その他の費用", oth)]:
        L.append("| %s | %s | %.1f%% |" % (k, format(round(v), ","), v / sales * 100 if sales else 0))
    est = [r for r in rows if r["状態"] != "実額"]
    L += ["", "実額にできた注文 %d件・見積のまま %d件%s" % (n - len(est), len(est), "（" + "・".join(r["SKU"] for r in est[:20]) + "）" if est else ""),
          "仕入値が答え（仕入れた）の注文 %d件・出品時の仕入値（見積）のまま %d件" % (sum(1 for r in rows if "答え" in r["仕入値の出どころ"]), sum(1 for r in rows if "答え" not in r["仕入値の出どころ"]))]
    if unmatched:
        L.append("明細にあって経理の台帳に無い注文 %d件（受注の通知を始める前の注文など）" % len(unmatched))
    # ④ 見積と実額のズレ
    ok = [r for r in rows if r["状態"] == "実額" and num(r["売上_円_実額"])]
    L += ["", "## 見積と実額のズレ（来月の見積式への反映案・変えるのはオーナーが言ってから）", ""]
    if ok:
        def ratio(a, b):
            sa, sb = sum(num(r[a]) or 0 for r in ok), sum(num(r[b]) or 0 for r in ok)
            return sa, sb
        sa_u = sum(num(r["売上_ドル"]) or 0 for r in ok)
        s_act = sum(num(r["売上_円_実額"]) or 0 for r in ok)
        fx_act = s_act / sa_u if sa_u else 0
        fee_act = sum((num(r["手数料_円_実額"]) or 0) + (num(r["広告_円_実額"]) or 0) for r in ok) / s_act if s_act else 0
        fee_est = sum(num(r["手数料_円_見積"]) or 0 for r in ok) / sum(num(r["売上_円_見積"]) or 0 for r in ok)
        sh_a, sh_e = ratio("送料_円_実額", "海外送料_円_見積")
        L += ["| 項目 | 見積 | 実額 | ズレ | 反映案 |", "|---|---|---|---|---|"]
        L.append("| 為替（円/ドル） | %.1f | %.1f | %+.1f%% | %s |" % (fx_m, fx_act, (fx_act / fx_m - 1) * 100 if fx_m else 0,
                 "店の設定 為替_円per米ドル を %.0f に" % fx_act if fx_m and abs(fx_act / fx_m - 1) > 0.03 else "このまま"))
        L.append("| 手数料＋広告の率 | %.1f%% | %.1f%% | %+.1fポイント | %s |" % (fee_est * 100, fee_act * 100, (fee_act - fee_est) * 100,
                 "手数料の率を %.1f%% に" % (fee_act * 100) if abs(fee_act - fee_est) > 0.01 else "このまま"))
        L.append("| 海外送料 | %s円 | %s円 | %+.1f%% | %s |" % (format(round(sh_e), ","), format(round(sh_a), ","), (sh_a / sh_e - 1) * 100 if sh_e else 0,
                 "送料の見積に 係数 %.2f を掛ける（大きくずれた型番は 実額_円_型番ごと に書く）" % (sh_a / sh_e) if sh_e and abs(sh_a / sh_e - 1) > 0.1 else "このまま"))
        big = sorted(ok, key=lambda r: -abs((num(r["利益_円_実額"]) or 0) - (num(r["利益_円_見積"]) or 0)))[:5]
        L += ["", "利益のズレが大きかった注文："] + ["- %s：見積 %s円 → 実額 %s円" % (r["SKU"], r["利益_円_見積"], r["利益_円_実額"]) for r in big]
    else:
        L.append("実額にできた注文が無いので、まだ比べられない。")
    # ⑤ 消費税の還付の見込み
    biz = sum((num(r["仕入値_円"]) or 0) + (num(r["国内送料_円"]) or 0) for r in rows if r["仕入先の区分"] == "事業者")
    per = [r for r in rows if r["仕入先の区分"] == "個人"]
    per_amt = sum((num(r["仕入値_円"]) or 0) + (num(r["国内送料_円"]) or 0) for r in per)
    tb = biz * 10 / 110
    tp_full = per_amt * 10 / 110
    tp_tr = sum(((num(r["仕入値_円"]) or 0) + (num(r["国内送料_円"]) or 0)) * 10 / 110 * tax_rate_person(r["仕入れた日"] or r["注文日_PT"]) for r in per)
    L += ["", "## 消費税の還付の見込み（一般課税の課税事業者として試算・申告は税理士に相談）", "",
          "輸出の売上は免税（0%）なので、国内の仕入れにふくまれる消費税（10/110）が還付の見込みになる。", "",
          "| 仕入れ先 | 仕入れ（税込） | 消費税の見込み |", "|---|---|---|",
          "| 事業者（楽天・Yahoo!ショッピング・店など） | %s円 | %s円 |" % (format(round(biz), ","), format(round(tb), ",")),
          "| 個人（フリマ・オークション）経過措置（2026/10/1から70%%） | %s円 | %s円 |" % (format(round(per_amt), ","), format(round(tp_tr), ",")),
          "| 個人：古物商特例が使えた場合（100%%） | %s円 | %s円 |" % (format(round(per_amt), ","), format(round(tp_full), ",")),
          "| **還付の見込み（少なめ〜多め）** | | **%s〜%s円** |" % (format(round(tb + tp_tr), ","), format(round(tb + tp_full), ",")), "",
          "- 仕入値が「仕入れた」の答えでない注文は、出品時の仕入値で見積もっている。",
          "- eBay の手数料・広告の消費税、梱包材などの経費は入れていない（税理士に確認）。",
          "- 古物商特例は、古物台帳に必要なこと（相手・品目・数量・代価など）を書いているときだけ。使えるかは税理士に確認。",
          "- 課税事業者でない・簡易課税・2割特例のときは、還付は出ない。"]
    md = "\n".join(L) + "\n"
    os.makedirs(os.path.join(D, "月次レポート"), exist_ok=True)
    open(os.path.join(D, "月次レポート", ym + ".md"), "w", encoding="utf-8").write(md)
    return md


if __name__ == "__main__":
    a = sys.argv[1:] or ["record"]
    if a[0] == "record":
        sys.exit(record())
    if a[0] == "import" and len(a) == 3:
        sys.exit(do_import(a[1], a[2]))
    if a[0] == "close" and len(a) == 2:
        sys.exit(close(a[1]))
    print(__doc__)
    sys.exit(2)

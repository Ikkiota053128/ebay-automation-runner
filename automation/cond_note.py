"""仕入れ先の「状態の説明」を読んで、短い英文にする（11/21 13:07 オーナー「1と3」）。
- 読むのは仕入れ先の説明文：楽天は公式API（itemCaption）、ほかの店・Yahoo!フリマ・ヤフオクは商品ページ。メルカリ・Amazon（人が集める品）は商品名だけ（ページを開かない）。
- 日本語の決まった言葉（ランク・美品・傷・動作確認済み・箱付きなど）を拾って英語にする。拾えた言葉だけを書き、無い事は書かない（うそを書かない）。
- 「動作確認済み」は仕入れ先がそう書いているときだけ（Reported working in the Japanese listing）。私たちが試したとは書かない。
返事：{"notes": [英文…], "func": 動作の文, "box": 付属の文 か ""}"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NEG = r"[^。\n]{0,12}?(?:なし|無し|ない|ありません|見られません|ございません)"


def _has(rx, t):
    return re.search(rx, t) is not None


def _absent(rx, t):
    """「カビ・クモリなし」のように、すぐ後ろで打ち消している"""
    return re.search("(?:%s)%s" % (rx, NEG), t) is not None


# 11/28 11:49 オーナー「見分けも直して」：動作確認済みの見分けを厳しくする（根拠の読み直しで見つかったまちがいの形）
WORK_RX = re.compile(r"動作確認済|動作品|正常に動作|動作OK|動作ok|動作良好|作動確認済|作動品|動作確認しております|動作を確認|ことを確認済")
# ① 関連キーワード・検索用・ハッシュタグの中の言葉は数えない
SEO_RX = re.compile(r"(関連キーワード|検索用|検索ワード|キーワード[:：]|#\S*動作)")
# ② 付属品のことを言っている（例：動作確認済みの互換バッテリー・電池ケース（動作確認済））
ACC_AFTER = re.compile(r"^(?:済み?|済|み)?\s*(?:の|な)\s*(?:互換|純正)?\s*(?:バッテリー|電池|充電器|アダプタ|ケーブル|リモコン|イヤホン|ケース|ストラップ|レンズ|フラッシュ)")
ACC_BEFORE = re.compile(r"(?:バッテリー|電池|充電器|アダプタ|ケーブル|リモコン|イヤホン|ケース|ストラップ)\s*[（(]?\s*$")
# ③ 質問の文（買い手のコメントなど）
QUESTION = re.compile(r"(でしょうか|ますか|ですか|[？?])")
# ④ 同じ文か近くに書いてある不具合（打ち消しの「なし・ありません」は数えない）
DEFECT_RX = re.compile(r"(異常|エラー|異音|ピントが合[いわ]ない|ピントが合いません|ノイズ|クモリ|曇り|白っぽ|戻りが悪|液晶.{0,4}劣化|画面.{0,2}劣化|(?<!があった場合は)不具合(?!があった|の場合|が(?:ございましたら|あれば))|難あり|難有|【難】|\s難\s|電源が落ち|ツメがな|反応しない|反応が悪|映らない|写らない|カビ|故障|ガリ|音が出ない|動かない|止まる|表示不良|表示しません|通電しません)")
NEG_RX = re.compile(r"^.{0,14}?(なし|無し|なく|ありません|見受けられません|見当たりません|ない|見られません|ございません|ゼロ|はなく|もなく)")


def working_ok(t):
    """仕入れ先が本当に「この品が動く」と書いているか。言葉があっても、①〜④に当たるものは数えない。1つも残らなければ False"""
    t = t or ""
    seo = SEO_RX.search(t)
    for m in WORK_RX.finditer(t):
        if seo and m.start() > seo.start():
            continue   # ①
        if ACC_AFTER.match(t[m.end():m.end() + 14]) or ACC_BEFORE.search(t[max(0, m.start() - 14):m.start()]):
            continue   # ②
        a = max(t.rfind("。", 0, m.start()), t.rfind("\n", 0, m.start()), t.rfind(" / ", 0, m.start()))
        e = [x for x in (t.find("。", m.end()), t.find("\n", m.end())) if x >= 0]
        sent = t[a + 1:(min(e) if e else m.end() + 80)]
        if QUESTION.search(sent):
            continue   # ③
        near = t[max(0, m.start() - 60):m.end() + 160]
        bad = [d for d in DEFECT_RX.finditer(near) if not NEG_RX.match(near[d.end():d.end() + 16])]
        if bad:
            return False   # ④ 動作確認済みでも、不具合が書いてある品は「動作確認済み」と言わない
        return True
    return False


def source_text(c, timeout_ok=True):
    """仕入れ先の説明文（無ければ ""）。失敗しても出品は止めない"""
    url = str(c.get("url", ""))
    try:
        if re.search(r"mercari|amazon\.", url) or str(c.get("id", "")).startswith("人:"):
            return ""
        if "item.rakuten.co.jp" in url:
            from stock_watch import _rk_call, _rk_norm
            key = _rk_norm(url)
            rid, acc = os.environ.get("RAKUTEN_APP_ID", "").strip(), os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
            relay, tok = os.environ.get("RAKUTEN_RELAY_URL", "").strip(), os.environ.get("RAKUTEN_RELAY_TOKEN", "").strip()
            if not (key and rid and acc and relay):
                return ""
            j, _ = _rk_call({"format": "json", "formatVersion": 2, "applicationId": rid, "availability": 0,
                             "itemCode": "%s:%s" % key, "hits": 1}, relay, acc, tok)
            for it in (j or {}).get("items") or (j or {}).get("Items") or []:
                it = it.get("Item", it)
                return "%s\n%s" % (it.get("itemName", ""), it.get("itemCaption", ""))
            return ""
        from stock_watch import fetch
        code, html = fetch(url)
        if code != 200 or not html:
            return ""
        html = html.replace("\\u002F", "/").replace("\\n", "\n")
        parts = re.findall(r'"description"\s*:\s*"([^"]{10,6000})"', html)
        parts += re.findall(r'<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]{10,3000})"', html)
        body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
        body = re.sub(r"<br\s*/?>|</p>|</li>|</tr>|</div>", "\n", body)
        body = re.sub(r"<[^>]+>", " ", body)
        # 状態の言葉の近くだけを取る（ページ全体の案内文・ほかの商品の文を拾わない）
        for m in re.finditer(r"(状態|コンディション|ランク|動作|付属|傷|キズ|商品説明)", body):
            parts.append(body[max(0, m.start() - 40): m.start() + 300])
        return "\n".join(parts)[:12000]
    except Exception:
        return ""


def notes(text, title=""):
    t = re.sub(r"[ \t　]+", " ", "%s\n%s" % (title or "", text or ""))
    out, box = [], []
    # ランク（店の付けたランク）
    m = re.search(r"(?:ランク|RANK|Rank)\s*[:：]?\s*([SABCDJ][+＋\-]?|AB|BC)(?![A-Za-z])", t) or \
        re.search(r"(?<![A-Za-z])([SABCD][+＋]?|AB|BC)\s*ランク", t)
    if m:
        out.append("Shop's condition rank: %s" % m.group(1).replace("＋", "+"))
    if _has(r"新品同様|未使用に近い|ほぼ新品|ほぼ未使用", t):
        out.append("Near mint (like new)")
    elif _has(r"未使用", t) and not _absent(r"未使用", t):
        out.append("Unused")
    elif _has(r"極美品|超美品", t):
        out.append("Excellent+ cosmetic condition")
    elif _has(r"美品", t):
        out.append("Excellent cosmetic condition")
    elif _has(r"良品", t):
        out.append("Good condition")
    elif _has(r"並品|使用感", t):
        out.append("Visible signs of use")
    # 見た目
    for rx, en in [(r"傷|キズ|スレ|擦れ", "Scratches or scuffs"), (r"打痕|凹み|へこみ", "Dents"), (r"汚れ|シミ", "Dirt or stains"),
                   (r"錆|サビ", "Rust"), (r"割れ|ヒビ|欠け", "Cracks or chips")]:
        if _has(rx, t) and not _absent(rx, t):
            out.append(en + " (see photos)")
    if _has(r"カビ|クモリ|曇り|バルサム", t):
        if _absent(r"カビ|クモリ|曇り|バルサム", t):
            out.append("No fungus or haze reported (lens)")
        else:
            out.append("Fungus or haze mentioned (lens) - see photos")
    # 動作
    func = ""
    if _has(r"ジャンク|動作未確認|動作不良|故障|部品取り", t):
        func = "Not tested / not guaranteed. Please check the photos."
    elif working_ok(t):
        func = "Reported working in the Japanese listing (not tested by us)."
    if _has(r"電池切れ|電池交換", t):
        out.append("Battery may need replacement")
    # 付属品
    if _has(r"本体のみ|箱なし|箱無し", t):
        box.append("Body only (no box)")
    elif _has(r"元箱|箱付|箱あり|外箱|化粧箱", t):
        box.append("Box")
    for rx, en in [(r"取扱説明書|説明書", "Manual"), (r"保証書", "Warranty card"), (r"充電器|チャージャー", "Charger"),
                   (r"レンズキャップ|キャップ", "Cap"), (r"ストラップ", "Strap"), (r"ケース付|ケースあり|ソフトケース|ハードケース", "Case")]:
        if _has(rx, t) and not _absent(rx, t) and en not in box:
            box.append(en)
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return {"notes": uniq[:8], "func": func, "box": ", ".join(box)}


def for_item(c):
    return notes(source_text(c), c.get("title", ""))


if __name__ == "__main__":
    print(json.dumps(notes(sys.argv[1] if len(sys.argv) > 1 else "中古 Aランク 美品 動作確認済み 小傷あり カビ・クモリなし 元箱 取扱説明書付"), ensure_ascii=False))

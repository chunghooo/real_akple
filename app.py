import streamlit as st
import pandas as pd
import hashlib
import json
from datetime import datetime, timezone
from collections import Counter

import collect
import detect
import report

st.set_page_config(page_title="EVIDA", page_icon="🛡️", layout="wide")

st.markdown(
    """
    <style>
    [data-testid='stToolbar'] { visibility: hidden; }
    .block-container { max-width: 1150px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛡️ EVIDA")
st.caption("AI 악플 분석 및 증거자료 생성 서비스 — 신고·고소 준비를 돕는 참고자료를 만들어 드립니다.")

c1, c2, c3 = st.columns(3)
with c1:
    with st.container(border=True):
        st.markdown("**① 넣기**\n\n유튜브 링크 또는 텍스트·스크린샷을 입력하세요.")
with c2:
    with st.container(border=True):
        st.markdown("**② 자동 분류**\n\n규칙 + 학습 AI로 먼저 분류하고, 애매한 것만 생성형 AI가 다시 검토합니다.")
with c3:
    with st.container(border=True):
        st.markdown("**③ 보고서 받기**\n\n증거를 선택하고 사건 정보를 입력하면 PDF로 받을 수 있습니다.")

st.text_input("피해자 이름·별명 (선택, 쉼표로 여러 개)", key="victim")


def _has_ocr():
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def _ocr_image_to_lines(img_bytes):
    from PIL import Image, ImageOps
    import io
    import pytesseract

    img = Image.open(io.BytesIO(img_bytes)).convert("L")
    avg = sum(img.getdata()) / (img.width * img.height)
    if avg < 128:
        img = ImageOps.invert(img)
    target_w = 1400
    scale = min(3.0, max(1.0, target_w / img.width))
    if scale > 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    text = pytesseract.image_to_string(img, lang="kor+eng", config="--psm 6")
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]

    noise_words = ["답글", "좋아요", "싫어요", "공유", "신고", "선택됨"]
    import re

    cleaned = []
    pending_author = None
    for line in raw_lines:
        if line.startswith("@"):
            pending_author = line.lstrip("@").strip()
            continue
        if line == "선택됨":
            continue
        if any(w in line for w in noise_words):
            continue
        if re.search(r"\d+\s*분\s*전", line):
            continue

        kor = len(re.findall(r"[가-힣]", line))
        words = line.split()
        upper_ratio = (
            sum(1 for ch in line if ch.isalpha() and ch.isupper()) / max(1, sum(1 for ch in line if ch.isalpha()))
        )
        ok = kor >= 2 or (len(words) >= 3 and upper_ratio < 0.5)
        if not ok:
            continue

        author = pending_author if pending_author else "미확인"
        pending_author = None
        cleaned.append(f"[@{author}] {line}")
    return cleaned


def _parse_text_lines(raw_text):
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for i, line in enumerate(raw_text.splitlines()):
        line = line.strip()
        if not line:
            continue
        author = "미확인"
        content = line
        if line.startswith("[@") and "]" in line:
            end = line.index("]")
            author = line[2:end].strip() or "미확인"
            content = line[end + 1:].strip()
        rows.append(
            {
                "id": f"txt_{i}",
                "author": author,
                "channel": "미확인",
                "cid": "미확인",
                "text": content,
                "time": now,
                "link": "미확인",
                "label": "미확인",
                "severity": 0,
                "category": "미확인",
                "reason": "미확인",
                "law": "미확인",
                "statute": "미확인",
                "ai": "미확인",
                "gem": "",
                "target": "",
                "memo": "",
            }
        )
    return rows


@st.cache_resource(show_spinner=False)
def _cached_model():
    return detect.train_model()


def _run_analysis(rows, raw_pages, src, url, imgs):
    if isinstance(raw_pages, (list, dict)):
        raw_bytes = json.dumps(raw_pages, ensure_ascii=False).encode("utf-8")
    elif isinstance(raw_pages, str):
        raw_bytes = raw_pages.encode("utf-8")
    elif raw_pages is None:
        raw_bytes = b""
    else:
        raw_bytes = raw_pages
    for r in rows:
        r.update(detect.classify(r["text"]))
    model = _cached_model()
    rows = detect.apply_model(rows, model)
    victim_raw = st.session_state.get("victim", "")
    names = [n.strip() for n in victim_raw.split(",") if n.strip()]
    if names:
        rows = detect.tag_victim(rows, names)

    img_bytes_all = b"".join(imgs) if imgs else b""
    sha = hashlib.sha256((raw_bytes or b"") + img_bytes_all).hexdigest()

    sel = {r["id"] for r in rows if r.get("severity", 0) >= 2}

    st.session_state["rows"] = rows
    st.session_state["raw"] = raw_bytes
    st.session_state["sha"] = sha
    st.session_state["at"] = datetime.now(timezone.utc).isoformat()
    st.session_state["src"] = src
    st.session_state["url"] = url
    st.session_state["imgs"] = imgs or []
    st.session_state["sel"] = sel
    st.session_state["memo"] = {}
    st.session_state["gcache"] = {}
    st.session_state["ver"] = st.session_state.get("ver", 0) + 1


tab1, tab2 = st.tabs(["🔗 유튜브 링크", "📋 텍스트·스크린샷"])

with tab1:
    has_key = "YOUTUBE_API_KEY" in st.secrets
    key_input = None
    cols = st.columns([3, 1, 1]) if has_key else st.columns([2, 2, 1, 1])
    if has_key:
        url_col, limit_col, btn_col = cols
    else:
        url_col, key_col, limit_col, btn_col = cols

    url = url_col.text_input("유튜브 주소", key="yt_url")
    if not has_key:
        key_input = key_col.text_input("YouTube API Key", key="yt_key", type="password")
    limit = limit_col.number_input("최대 수집 수", min_value=100, max_value=50000, value=3000, step=100)
    start = btn_col.button("수집 시작", key="yt_start")

    if start:
        api_key = st.secrets.get("YOUTUBE_API_KEY") if has_key else key_input
        if not api_key:
            st.error("YouTube API Key가 필요합니다.")
        else:
            vid = collect.video_id(url)
            if not vid:
                st.error("올바른 유튜브 주소가 아닙니다.")
            else:
                progress = st.progress(0, text="댓글 0개 수집 중…")

                def _progress(n, total=None):
                    pct = 0
                    if total:
                        pct = min(100, int(n / total * 100))
                    progress.progress(pct, text=f"댓글 {n}개 수집 중…")

                try:
                    rows, raw_pages = collect.fetch(vid, api_key, int(limit), progress=_progress)
                    progress.empty()
                    _run_analysis(rows, raw_pages, "유튜브", url, [])
                    st.success(f"{len(rows)}개 댓글을 수집했습니다.")
                except Exception as e:
                    progress.empty()
                    st.error(f"수집 중 오류가 발생했습니다: {e}")

with tab2:
    left, right = st.columns(2)
    with left:
        imgs_up = st.file_uploader(
            "스크린샷 업로드", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="imgs_up"
        )
        ocr_btn = st.button("사진에서 글자 읽기", key="ocr_btn")
        if ocr_btn:
            if not imgs_up:
                st.error("이미지를 먼저 업로드해 주세요.")
            elif not _has_ocr():
                st.error("이 환경에서는 글자 인식 기능을 사용할 수 없습니다.")
            else:
                all_lines = []
                for f in imgs_up:
                    try:
                        all_lines.extend(_ocr_image_to_lines(f.getvalue()))
                    except Exception as e:
                        st.error(f"이미지 처리 중 오류: {e}")
                prev = st.session_state.get("txt", "")
                joined = "\n".join(all_lines)
                st.session_state["txt"] = (prev + "\n" + joined).strip() if prev else joined

    with right:
        st.text_area(
            "텍스트 (한 줄에 하나, 예: [@아이디] 내용)", key="txt", height=280
        )
        classify_btn = st.button("분류하기", key="classify_btn")
        if classify_btn:
            raw_text = st.session_state.get("txt", "")
            if not raw_text.strip():
                st.error("분류할 텍스트가 없습니다.")
            else:
                rows = _parse_text_lines(raw_text)
                img_bytes_list = [f.getvalue() for f in (imgs_up or [])]
                _run_analysis(rows, raw_text.encode("utf-8"), "직접 입력", "", img_bytes_list)
                st.success(f"{len(rows)}개 댓글을 분류했습니다.")

rows = st.session_state.get("rows")

if rows:
    for r in rows:
        if r.get("label") in (None, ""):
            continue
        res = detect.classify(r["text"])
        r.setdefault("category", res.get("category", "미확인"))

    sel = st.session_state.get("sel", set())
    ai_found = sum(1 for r in rows if "AI 판단" in str(r.get("category", "")))

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("출처", st.session_state.get("src", "미확인"))
    m2.metric("전체", len(rows))
    m3.metric("악플 후보", sum(1 for r in rows if r.get("label") == "악플"))
    m4.metric("그중 AI가 찾은 것", ai_found)

    with st.expander("📊 악플 현황 (유형 · 상습 작성자 · 날짜별 추이)", expanded=True):
        bad_rows = [r for r in rows if r.get("severity", 0) >= 2]
        if not bad_rows:
            st.info("아직 악플 후보가 없습니다.")
        else:
            cat_counter = Counter(r.get("category", "미확인") for r in bad_rows)
            cat_df = pd.DataFrame(
                {"유형": list(cat_counter.keys()), "건수": list(cat_counter.values())}
            ).set_index("유형")
            st.bar_chart(cat_df, color="#FF4B4B")

            author_counter = Counter(r.get("author", "미확인") for r in bad_rows)
            top5 = author_counter.most_common(5)
            st.table(pd.DataFrame(top5, columns=["작성자", "악플 수"]))

            text_counter = Counter(r["text"] for r in bad_rows if len(r["text"]) >= 5)
            if any(v >= 3 for v in text_counter.values()):
                st.warning("📋 같은 내용 반복 — 도배·조직적 공격 의심")

            dates_all = Counter()
            dates_bad = Counter()
            for r in rows:
                try:
                    d = r["time"][:10]
                except Exception:
                    d = "미확인"
                dates_all[d] += 1
                if r.get("severity", 0) >= 2:
                    dates_bad[d] += 1
            all_dates = sorted(dates_all.keys())
            date_df = pd.DataFrame(
                {
                    "전체": [dates_all.get(d, 0) for d in all_dates],
                    "악플": [dates_bad.get(d, 0) for d in all_dates],
                },
                index=all_dates,
            )
            st.bar_chart(date_df, color=["#AAAAAA", "#FF4B4B"], stack=False)

            st.caption(
                "학습 데이터 출처: UnSmile (CC BY-NC-ND 4.0), K-MHaS (CC BY-SA 4.0)"
            )

    with st.expander("🤖 생성형 AI 2차 검토 (Gemini)", expanded=False):
        gem_key = st.secrets.get("GEMINI_API_KEY")
        if not gem_key:
            st.info("GEMINI_API_KEY가 설정되지 않아 생성형 AI 2차 검토를 사용할 수 없습니다.")
        else:
            scope = st.radio(
                "검토 범위", ["애매한 것만 (절약)", "악플 후보 전부 (정밀)"], key="gem_scope"
            )
            consent = True
            if st.session_state.get("src") == "직접 입력":
                consent = st.checkbox("구글로 전송 동의", key="gem_consent")

            def _is_target(r):
                if scope == "악플 후보 전부 (정밀)":
                    return r.get("severity", 0) >= 2
                bad_ambiguous = r.get("severity", 0) >= 2 and (
                    r.get("severity") == 1 or _ai_score(r) < 50
                )
                normal_mid = r.get("severity", 0) == 0 and 40 <= _ai_score(r) <= 64
                return bad_ambiguous or normal_mid

            def _ai_score(r):
                try:
                    return float(r.get("ai", 0))
                except Exception:
                    return 0.0

            gcache = st.session_state.get("gcache", {})
            candidates = [r for r in rows if _is_target(r)]
            seen_text = set()
            dedup = []
            for r in candidates:
                if r["text"] in seen_text:
                    continue
                seen_text.add(r["text"])
                dedup.append(r)
            dedup = dedup[:200]
            to_send = [r for r in dedup if r["id"] not in gcache]
            st.write(f"새로 보낼 것 {len(to_send)}개 (요청 약 {max(1, -(-len(to_send)//50))}회)")

            run_gem = st.button("생성형 AI 검토 실행", key="gem_run", disabled=not consent)
            if run_gem:
                import requests

                instruction = (
                    "너는 한국어 댓글이 특정인을 향한 악플인지 판단하는 검토자야. "
                    "악플: 특정인·집단을 겨냥한 모욕, 비하, 조롱, 비꼬기·반어, 외모 비하, 위협, 성희롱, 2차 가해, 근거 없는 의혹. "
                    "아님: 칭찬·감탄 속 욕(예: 노래 지린다 ㅅㅂ), 혼잣말 감탄(예: 죽는 줄 알았다 이새끼), 자기 비하, "
                    "사물·상황에 대한 욕, 게임·스포츠 플레이 묘사, 인용·신고, 예의 있는 비판. "
                    "욕이 섞여도 특정인을 깎아내리지 않으면 아님, 욕이 없어도 특정인을 깎아내리면 악플. "
                    'JSON 배열로만 답해: [{"i": 번호, "v": "악플" 또는 "아님", "r": "15자 이내 이유"}]'
                )
                try:
                    list_resp = requests.get(
                        f"https://generativelanguage.googleapis.com/v1beta/models?key={gem_key}",
                        timeout=20,
                    )
                    models = list_resp.json().get("models", [])
                    candidates_m = [
                        m["name"] for m in models
                        if "generateContent" in m.get("supportedGenerationMethods", [])
                    ]
                    candidates_m = [m for m in candidates_m
                                    if not any(x in m for x in ("tts", "image", "audio", "live", "embedding", "thinking"))]
                    flash_lite = [m for m in candidates_m if "flash-lite" in m]
                    flash = [m for m in candidates_m if "flash" in m and "lite" not in m]
                    model_name = (flash_lite or flash or candidates_m)[-1]

                    hit_limit = False
                    for i in range(0, len(to_send), 50):
                        batch = to_send[i:i + 50]
                        payload_text = instruction + "\n\n" + json.dumps(
                            [{"i": idx, "t": r["text"]} for idx, r in enumerate(batch)],
                            ensure_ascii=False,
                        )
                        resp = requests.post(
                            f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={gem_key}",
                            json={
                                "contents": [{"parts": [{"text": payload_text}]}],
                                "generationConfig": {
                                    "temperature": 0,
                                    "responseMimeType": "application/json",
                                },
                                # 악플 원문을 검토해야 하므로 안전 필터가 요청 자체를 막지 않게 함
                                "safetySettings": [
                                    {"category": c, "threshold": "BLOCK_NONE"}
                                    for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                                              "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
                                ],
                            },
                            timeout=60,
                        )
                        if resp.status_code == 429:
                            st.error("오늘 Gemini 무료 사용량을 다 썼어요.")
                            hit_limit = True
                            break
                        data = resp.json()
                        if resp.status_code != 200:
                            st.error(f"Gemini 오류({resp.status_code}): {data.get('error', {}).get('message', '')} · 모델 {model_name}")
                            hit_limit = True
                            break
                        if not data.get("candidates"):
                            st.error(f"Gemini가 응답을 거부했어요: {data.get('promptFeedback', {}).get('blockReason', '이유 미상')} · 모델 {model_name}")
                            hit_limit = True
                            break
                        text_out = data["candidates"][0]["content"]["parts"][0]["text"]
                        text_out = text_out[text_out.find("["):text_out.rfind("]") + 1]
                        results = json.loads(text_out)
                        for item in results:
                            idx = item.get("i")
                            if idx is None or idx >= len(batch):
                                continue
                            r = batch[idx]
                            verdict = item.get("v")
                            reason = item.get("r", "")
                            if verdict == "악플":
                                r["gem"] = f"🔴 악플: {reason}"
                                r["severity"] = max(r.get("severity", 0), 2)
                                sel.add(r["id"])
                            else:
                                r["gem"] = f"🟢 아님: {reason}"
                                if r.get("severity", 0) >= 2 and r.get("category") != "신상노출":
                                    r["severity"] = 1
                                    sel.discard(r["id"])
                            gcache[r["id"]] = True
                    st.session_state["gcache"] = gcache
                    st.session_state["sel"] = sel
                    if not hit_limit:
                        st.session_state["ver"] = st.session_state.get("ver", 0) + 1
                        st.rerun()
                except Exception as e:
                    st.error(f"생성형 AI 검토 중 오류: {e}")

    st.markdown("---")
    f1, f2, f3, f4 = st.columns(4)
    scope_filter = f1.selectbox("범위", ["악플만", "전체 댓글", "선택한 것만"], key="scope_filter")
    all_cats = sorted({r.get("category", "미확인") for r in rows})
    cat_filter = f2.multiselect("유형", all_cats, key="cat_filter")
    search_filter = f3.text_input("검색어 (쉼표로 여러 개)", key="search_filter")
    try:
        all_dates = [r["time"][:10] for r in rows]
        min_d = min(all_dates)
        max_d = max(all_dates)
    except Exception:
        min_d = max_d = None
    date_range = f4.date_input(
        "작성 날짜 범위",
        value=(pd.to_datetime(min_d), pd.to_datetime(max_d)) if min_d else None,
        key="date_filter",
    )

    def _passes_filter(r):
        if scope_filter == "악플만" and r.get("label") != "악플":
            return False
        if scope_filter == "선택한 것만" and r["id"] not in sel:
            return False
        if cat_filter and not any(c in str(r.get("category", "")) for c in cat_filter):
            return False
        if search_filter:
            words = [w.strip() for w in search_filter.split(",") if w.strip()]
            if words and not any(detect.find_word(w, r["text"]) for w in words):
                return False
        if isinstance(date_range, tuple) and len(date_range) == 2:
            try:
                d = pd.to_datetime(r["time"][:10])
                if not (date_range[0] <= d.date() <= date_range[1]):
                    return False
            except Exception:
                pass
        return True

    filtered = [r for r in rows if _passes_filter(r)]

    def _kst(iso_str):
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            dt = dt.astimezone(timezone.utc)
            from datetime import timedelta

            dt_kst = dt + timedelta(hours=9)
            return dt_kst.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "미확인"

    memo = st.session_state.get("memo", {})

    table_data = []
    for r in filtered:
        table_data.append(
            {
                "id": r["id"],
                "포함": r["id"] in sel,
                "심각도": r.get("severity", 0),
                "법적 검토": r.get("law", "미확인"),
                "지목": r.get("target", ""),
                "작성자": r.get("author", "미확인"),
                "작성 시각": _kst(r.get("time", "")),
                "내용": r.get("text", ""),
                "메모": memo.get(r["id"], r.get("memo", "")),
                "판단 근거": r.get("reason", "미확인"),
                "AI 점수": r.get("ai", "미확인"),
                "생성형 AI 의견": r.get("gem", ""),
                "원문": r.get("link", "미확인") if st.session_state.get("src") == "유튜브" else "미확인",
            }
        )

    df = pd.DataFrame(table_data)
    editor_key = f"editor_{st.session_state.get('ver', 0)}_{scope_filter}_{','.join(cat_filter)}_{search_filter}"

    column_config = {
        "id": None,
        "원문": st.column_config.LinkColumn("원문", display_text="열기"),
    }

    edited = st.data_editor(
        df,
        key=editor_key,
        column_config=column_config,
        disabled=[c for c in df.columns if c not in ("포함", "메모")],
        hide_index=True,
    )

    new_sel = set(sel)
    for _, row in edited.iterrows():
        rid = row["id"]
        if row["포함"]:
            new_sel.add(rid)
        else:
            new_sel.discard(rid)
        memo[rid] = row["메모"]
    st.session_state["sel"] = new_sel
    st.session_state["memo"] = memo
    sel = new_sel

    st.caption(
        f"{len(filtered)}개 표시 · ✅ 현재 선택 {len(sel)}건 · 심각도 1 = 애매함(직접 판단) · 2 = 명백한 모욕 · 3 = 심각"
    )

    selected_rows = [r for r in rows if r["id"] in sel]
    for r in selected_rows:
        if r.get("severity", 0) == 0:
            r["category"] = "사용자 선택"
            r["law"] = "검토 필요"
        r["memo"] = memo.get(r["id"], r.get("memo", ""))
    selected_rows.sort(key=lambda r: r.get("time", ""))

    st.markdown("### 선택 목록")
    if selected_rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "작성 시각": _kst(r.get("time", "")),
                        "작성자": r.get("author", "미확인"),
                        "내용": r.get("text", ""),
                        "메모": r.get("memo", ""),
                    }
                    for r in selected_rows
                ]
            ),
            hide_index=True,
        )
    else:
        st.info("선택된 댓글이 없습니다.")

    st.divider()
    header_col, info_col = st.columns([2, 1])
    header_col.subheader("📄 증거자료 생성")
    info_col.info("이 보고서는 경찰청 공식 서식이 아닌, 신고 및 고소 준비를 위한 참고자료입니다.")

    box1, box2 = st.columns(2)
    with box1:
        with st.container(border=True):
            st.markdown("**① 기본 정보 입력**")
            case_title = st.text_input("사건명*", key="case_title")
            platform_default = "YouTube" if st.session_state.get("src") == "유튜브" else "기타"
            platform_options = ["YouTube", "Instagram", "KakaoTalk", "기타"]
            platform = st.selectbox(
                "플랫폼*",
                platform_options,
                index=platform_options.index(platform_default) if platform_default in platform_options else 0,
                key="case_platform",
            )
            st.number_input(
                "분석된 악성 댓글 수", value=len(selected_rows), disabled=True, key="case_count"
            )
            try:
                sel_dates = sorted(r["time"][:10] for r in selected_rows)
                default_range = (
                    (pd.to_datetime(sel_dates[0]), pd.to_datetime(sel_dates[-1]))
                    if sel_dates
                    else None
                )
            except Exception:
                default_range = None
            case_period = st.date_input(
                "피해 발생 기간",
                value=default_range,
                format="YYYY.MM.DD",
                key="case_period",
            )

    with box2:
        with st.container(border=True):
            st.markdown("**② 사건 내용 작성**")
            case_story = st.text_area(
                "피해 발생 경위*",
                placeholder="예: 2025년 1월경 유튜브 댓글을 통해 지속적인 모욕을 당함",
                key="case_story",
            )
            case_harm = st.text_area(
                "피해 내용*",
                placeholder="예: 반복적인 모욕으로 정신적 고통을 겪음",
                key="case_harm",
            )
            case_note = st.text_area("추가 설명 (선택)", key="case_note")

    with st.expander("③ 보고서 미리보기"):
        period_str = "미확인"
        if isinstance(case_period, tuple) and len(case_period) == 2:
            period_str = f"{case_period[0].strftime('%Y.%m.%d')} ~ {case_period[1].strftime('%Y.%m.%d')}"
        st.write(
            f"**{case_title or '미확인'}** · {platform} · {period_str} · {len(selected_rows)}건"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "번호": i + 1,
                        "작성자": r.get("author", "미확인"),
                        "작성 시각": _kst(r.get("time", "")),
                        "원문": r.get("text", ""),
                        "URL": r.get("link", "미확인"),
                    }
                    for i, r in enumerate(selected_rows)
                ]
            ),
            hide_index=True,
        )

    with st.container(border=True):
        st.markdown("**④ PDF 다운로드**")
        missing = []
        if not selected_rows:
            missing.append("증거 선택")
        if not case_story:
            missing.append("피해 발생 경위")
        if not case_harm:
            missing.append("피해 내용")

        if missing:
            st.warning(f"빠진 필수 항목이 있습니다: {', '.join(missing)}")
            st.button("⬇️ 증거 정리 보고서 다운로드", disabled=True, type="primary")
        else:
            meta = {
                "src": st.session_state.get("src", "미확인"),
                "url": st.session_state.get("url", ""),
                "collected_at": st.session_state.get("at", ""),
                "sha256": st.session_state.get("sha", ""),
                "total": len(rows),
                "images": st.session_state.get("imgs", []),
            }
            case = {
                "title": case_title,
                "platform": platform,
                "period": period_str,
                "story": case_story,
                "harm": case_harm,
                "note": case_note,
            }
            try:
                pdf_bytes = report.make_pdf(selected_rows, meta, case)
                st.download_button(
                    "⬇️ 증거 정리 보고서 다운로드",
                    data=pdf_bytes,
                    file_name="EVIDA_증거정리보고서.pdf",
                    mime="application/pdf",
                    type="primary",
                )
            except Exception as e:
                st.error(f"PDF 생성 중 오류가 발생했습니다: {e}")

    csv_df = pd.DataFrame(
        [
            {
                "작성자": r.get("author", "미확인"),
                "작성 시각": _kst(r.get("time", "")),
                "내용": r.get("text", ""),
                "심각도": r.get("severity", 0),
                "유형": r.get("category", "미확인"),
            }
            for r in rows
        ]
    )
    csv_bytes = csv_df.to_csv(index=False).encode("utf-8-sig")
    json_bytes = json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8")

    dl1, dl2 = st.columns(2)
    dl1.download_button("전체 목록 CSV", data=csv_bytes, file_name="evida_전체목록.csv", mime="text/csv")
    dl2.download_button(
        "원본 데이터 (JSON)", data=json_bytes, file_name="evida_원본데이터.json", mime="application/json"
    )
    st.caption(f"원본 SHA-256: {st.session_state.get('sha', '미확인')}")

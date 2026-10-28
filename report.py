# report.py — EVIDA 증거 정리 보고서 PDF 생성 (ReportLab)
import io
import os
import re
import hashlib
from collections import Counter
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, KeepTogether, Image,
)
from reportlab.lib.styles import ParagraphStyle

# ----------------------------------------------------------------------------
# 폰트
# ----------------------------------------------------------------------------
FONT_DIR = "/usr/share/fonts/truetype/nanum/"
KR_PATH = os.path.join(FONT_DIR, "NanumGothic.ttf")
KRB_PATH = os.path.join(FONT_DIR, "NanumGothicBold.ttf")

_KR_FONT = "Helvetica"
_KRB_FONT = "Helvetica-Bold"
_FONTS_READY = False


def _register_fonts():
    global _KR_FONT, _KRB_FONT, _FONTS_READY
    if _FONTS_READY:
        return
    try:
        if os.path.exists(KR_PATH):
            pdfmetrics.registerFont(TTFont("KR", KR_PATH))
            _KR_FONT = "KR"
        if os.path.exists(KRB_PATH):
            pdfmetrics.registerFont(TTFont("KRB", KRB_PATH))
            _KRB_FONT = "KRB"
        elif _KR_FONT == "KR":
            _KRB_FONT = "KR"
    except Exception:
        pass
    _FONTS_READY = True


# ----------------------------------------------------------------------------
# 색상
# ----------------------------------------------------------------------------
C_TEXT = HexColor("#111827")
C_SUB = HexColor("#6B7280")
C_LINE = HexColor("#D1D5DB")
C_TABLEHEAD = HexColor("#F3F4F6")
C_BOXBG = HexColor("#F9FAFB")
C_LAVENDER = HexColor("#E8EAFD")
C_LINK = HexColor("#3B3FD8")

KST = timezone(timedelta(hours=9))

EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\uFE0F\u2764]+"
)


def _sanitize(text):
    return EMOJI_PATTERN.sub(lambda m: "□" * len(m.group()), text or "")


def _esc(text):
    return escape(_sanitize(text or ""))


def _p(text, style):
    t = _esc(text).replace("\n", "<br/>")
    return Paragraph(t, style)


def _v(val, default="미확인"):
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def _fmt_kst(iso_str):
    if not iso_str:
        return "미확인"
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST).strftime("%Y.%m.%d %H:%M")
    except Exception:
        return "미확인"


def _fmt_kst_utc(iso_str):
    if not iso_str:
        return "미확인"
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst = dt.astimezone(KST)
        utc = dt.astimezone(timezone.utc)
        return f"{kst.strftime('%Y.%m.%d %H:%M')} KST (UTC {utc.strftime('%Y.%m.%d %H:%M')})"
    except Exception:
        return "미확인"


# ----------------------------------------------------------------------------
# 스타일
# ----------------------------------------------------------------------------
def _get_styles():
    return {
        "section": ParagraphStyle("section", fontName=_KRB_FONT, fontSize=12,
                                   textColor=C_TEXT, spaceBefore=10, spaceAfter=6, wordWrap="CJK"),
        "body": ParagraphStyle("body", fontName=_KR_FONT, fontSize=9.5,
                                textColor=C_TEXT, leading=14, wordWrap="CJK"),
        "gray": ParagraphStyle("gray", fontName=_KR_FONT, fontSize=9,
                                textColor=C_SUB, leading=13, wordWrap="CJK"),
        "small": ParagraphStyle("small", fontName=_KR_FONT, fontSize=7,
                                 textColor=C_SUB, leading=10, wordWrap="CJK"),
        "link": ParagraphStyle("link", fontName=_KR_FONT, fontSize=7,
                                textColor=C_LINK, leading=10, wordWrap="CJK"),
        "cell": ParagraphStyle("cell", fontName=_KR_FONT, fontSize=9,
                                textColor=C_TEXT, leading=13, wordWrap="CJK"),
        "cellhead": ParagraphStyle("cellhead", fontName=_KRB_FONT, fontSize=9,
                                    textColor=C_TEXT, leading=13, wordWrap="CJK"),
        "band": ParagraphStyle("band", fontName=_KRB_FONT, fontSize=10,
                                textColor=C_TEXT, leading=13, wordWrap="CJK"),
    }


def _box_table(flowable, width=17 * cm, bg=C_BOXBG, border=True):
    t = Table([[flowable]], colWidths=[width])
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    if border:
        style.append(("BOX", (0, 0), (-1, -1), 0.5, C_LINE))
    t.setStyle(TableStyle(style))
    return t


def _kv_table(rows, left_w=4.2 * cm, right_w=12.8 * cm):
    t = Table(rows, colWidths=[left_w, right_w])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), C_TABLEHEAD),
        ("GRID", (0, 0), (-1, -1), 0.5, C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ----------------------------------------------------------------------------
# 머리말 / 꼬리말
# ----------------------------------------------------------------------------
def _header_footer(canvas, doc):
    _register_fonts()
    canvas.saveState()
    width, height = A4
    canvas.setFont(_KRB_FONT, 15)
    canvas.setFillColor(C_TEXT)
    canvas.drawCentredString(width / 2, height - 1.6 * cm, "EVIDA 증거 정리 보고서")
    canvas.setFont(_KR_FONT, 8.5)
    canvas.setFillColor(C_SUB)
    canvas.drawCentredString(width / 2, height - 1.6 * cm - 0.45 * cm, "신고 및 고소 준비 참고자료")

    y_line = 1.5 * cm
    canvas.setStrokeColor(C_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, y_line, width - 2 * cm, y_line)
    canvas.setFont(_KR_FONT, 7.5)
    canvas.setFillColor(C_SUB)
    canvas.drawString(2 * cm, y_line - 0.35 * cm, "EVIDA | AI 악플 분석 및 증거자료 생성 서비스")
    canvas.drawRightString(width - 2 * cm, y_line - 0.35 * cm, str(doc.page))
    canvas.restoreState()


# ----------------------------------------------------------------------------
# 1쪽
# ----------------------------------------------------------------------------
def _build_page1(case, n_total, styles):
    flow = [Paragraph("1. 사건 개요", styles["section"])]
    rows = [
        [_p("사건명", styles["cellhead"]), _p(_v(case.get("title"), "온라인 댓글 관련 증거 정리"), styles["cell"])],
        [_p("플랫폼", styles["cellhead"]), _p(_v(case.get("platform")), styles["cell"])],
        [_p("분석된 악성 댓글 수", styles["cellhead"]), _p(f"{n_total}건", styles["cell"])],
        [_p("피해 발생 기간", styles["cellhead"]), _p(_v(case.get("period")), styles["cell"])],
    ]
    flow.append(_kv_table(rows))
    flow.append(Spacer(1, 10))

    def gray_section(title, content, empty_text="미기재"):
        flow.append(Paragraph(title, styles["section"]))
        text = (content or "").strip()
        inner = Paragraph(empty_text, styles["gray"]) if not text else _p(text, styles["body"])
        flow.append(_box_table(inner))
        flow.append(Spacer(1, 10))

    gray_section("2. 피해 발생 경위", case.get("story"))
    gray_section("3. 피해 내용", case.get("harm"))
    gray_section("4. 추가 설명", case.get("note"), empty_text="기타 참고할 내용 없음")
    return flow


# ----------------------------------------------------------------------------
# 2쪽: 일람표
# ----------------------------------------------------------------------------
def _build_list_table(selected, meta, styles):
    flow = [Paragraph("5. 악성 댓글 증거 일람표", styles["section"])]
    header = [_p(h, styles["cellhead"]) for h in ("번호", "작성자", "작성 시각", "댓글 원문", "URL")]
    data = [header]
    for i, c in enumerate(selected):
        url = c.get("link") or ""
        if url:
            url_cell = Paragraph(f'<link href="{_esc(url)}">{_esc(url)}</link>', styles["link"])
        else:
            url_cell = Paragraph("미확인", styles["gray"])
        data.append([
            _p(f"{i + 1:03d}", styles["cell"]),
            _p(_v(c.get("author")), styles["cell"]),
            _p(_fmt_kst(c.get("time")), styles["cell"]),
            _p(c.get("text") or "미확인", styles["cell"]),
            url_cell,
        ])
    t = Table(data, colWidths=[1.1 * cm, 2.6 * cm, 2.3 * cm, 6.2 * cm, 4.8 * cm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_TABLEHEAD),
        ("GRID", (0, 0), (-1, -1), 0.5, C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 6))
    total = meta.get("total", len(selected))
    flow.append(Paragraph(f"※ 총 {len(selected)}건의 악성 댓글이 증거로 선택되었습니다. (전체 수집 댓글 {total}건)", styles["gray"]))
    return flow


# ----------------------------------------------------------------------------
# 3쪽~: 개별 증거
# ----------------------------------------------------------------------------
def _build_evidence_page(c, idx, meta, styles):
    flow = []
    band = Table([[Paragraph(f"증거번호 EV-{idx:03d}", styles["band"])]], colWidths=[17 * cm])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_LAVENDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(band)
    flow.append(Spacer(1, 8))

    is_youtube = meta.get("src") == "youtube"
    rows = [
        [_p("작성자", styles["cellhead"]), _p(_v(c.get("author")), styles["cell"])],
        [_p("작성 시각", styles["cellhead"]), _p(_fmt_kst_utc(c.get("time")), styles["cell"])],
        [_p("댓글 원문", styles["cellhead"]), _p(c.get("text") or "미확인", styles["cell"])],
        [_p("댓글 ID", styles["cellhead"]), _p(_v(c.get("cid")) if is_youtube else "미확인", styles["cell"])],
        [_p("작성자 채널 ID", styles["cellhead"]), _p(_v(c.get("channel")), styles["cell"])],
    ]
    url = c.get("link") or ""
    if url:
        url_cell = Paragraph(f'<link href="{_esc(url)}">{_esc(url)}</link>', styles["cell"])
    else:
        url_cell = Paragraph("미확인", styles["cell"])
    rows.append([_p("원본 URL", styles["cellhead"]), url_cell])
    if c.get("memo"):
        rows.append([_p("사용자 메모", styles["cellhead"]), _p(c.get("memo"), styles["cell"])])
    flow.append(_kv_table(rows))
    flow.append(Spacer(1, 10))

    cap_title = ("댓글 화면 재구성 (API 원본 데이터 기반 · 실제 화면 캡처 아님)"
                 if is_youtube else "원본 캡처 이미지")
    flow.append(Paragraph(cap_title, styles["section"]))
    author = _esc(_v(c.get("author")))
    time_s = _esc(_fmt_kst(c.get("time")))
    body = _esc(c.get("text") or "미확인").replace("\n", "<br/>")
    card_html = f"<b>{author}</b> · {time_s}<br/>{body}<br/><font color='#6B7280'>좋아요 · 싫어요 · 답글</font>"
    dot_style = ParagraphStyle("dot", fontName=_KR_FONT, fontSize=18, textColor=C_LAVENDER)
    card = Table([[Paragraph("●", dot_style), Paragraph(card_html, styles["cell"])]],
                 colWidths=[1.2 * cm, 15.8 * cm])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow.append(card)
    flow.append(Spacer(1, 10))

    flow.append(Paragraph("AI 분석 참고사항", styles["section"]))
    extra = []
    if c.get("reason"):
        extra.append(f"근거: {c['reason']}")
    ai_val = c.get("ai")
    if ai_val not in (None, ""):
        try:
            f = float(ai_val)
            pct = int(round(f * 100)) if f <= 1 else int(round(f))
            extra.append(f"AI 점수 {pct}%")
        except Exception:
            pass
    if c.get("gem"):
        extra.append(f"생성형 AI 의견: {c['gem']}")
    if c.get("statute"):
        extra.append(f"관련 조항: {c['statute']}")
    line = " · ".join(extra)
    law = c.get("law") or ""
    if law and line:
        full = f"{law} — {line}"
    else:
        full = law or line or "참고 정보 없음"
    full = full.replace("🔴", "").replace("🟢", "")
    ai_text = full + "\n(본 내용은 참고용이며, 실제 법적 판단은 수사기관의 결정에 따릅니다.)"
    flow.append(_box_table(_p(ai_text, styles["cell"]), bg=C_LAVENDER, border=False))
    return flow


# ----------------------------------------------------------------------------
# 첨부 이미지
# ----------------------------------------------------------------------------
def _build_attachments(images, styles):
    flow = [Paragraph("원본 캡처 이미지 (사용자 첨부)", styles["section"])]
    for img_bytes in images:
        sha = hashlib.sha256(img_bytes).hexdigest()
        flow.append(Paragraph(f"SHA-256: {sha}", styles["small"]))
        try:
            reader = ImageReader(io.BytesIO(img_bytes))
            iw, ih = reader.getSize()
            max_w, max_h = 17 * cm, 21 * cm
            scale = min(max_w / iw, max_h / ih, 1.0) if iw and ih else 1.0
            flow.append(Image(io.BytesIO(img_bytes), width=iw * scale, height=ih * scale))
        except Exception:
            flow.append(Paragraph("이미지를 불러올 수 없습니다.", styles["gray"]))
        flow.append(Spacer(1, 12))
    return flow


# ----------------------------------------------------------------------------
# 7. 확인 사항
# ----------------------------------------------------------------------------
def _build_conclusion(selected, meta, styles):
    content = [Paragraph("7. 확인 사항 및 자료의 한계", styles["section"])]
    counter = Counter(_v(c.get("author"), "미확인") for c in selected)
    repeats = [f"{a} {n}건" for a, n in counter.items() if n >= 2 and a != "미확인"]

    lines = []
    if repeats:
        lines.append("반복 작성자: " + ", ".join(repeats))
    lines += [
        "□ 공연성",
        "□ 특정성",
        "□ 고소 기간 (모욕죄는 범인을 안 날부터 6개월, 친고죄)",
        "□ 사실 주장은 사실·거짓 구분 진술",
        "- 경찰청 공식 서식이 아닙니다.",
    ]
    if meta.get("src") == "youtube":
        lines.append("- 수집 방법: Google YouTube Data API v3 공식 서버 응답을 가공 없이 원본(JSON)으로 저장하고 그 원본에서 추출")
    else:
        lines.append("- 수집 방법: 사용자 직접 입력·스크린샷 글자 인식")
    lines.append(f"- 수집 일시(KST·UTC): {_v(meta.get('collected_at'))} · 원본 SHA-256: {_v(meta.get('sha256'))}")
    lines.append("- '미확인'은 값이 존재하지 않거나 수집되지 않았음을 의미하며, 원본 URL 화면 캡처를 함께 보관할 것을 권장합니다.")

    content.append(_p("\n".join(lines), styles["body"]))
    return [KeepTogether(content)]


# ----------------------------------------------------------------------------
# 진입점
# ----------------------------------------------------------------------------
def make_pdf(selected, meta, case):
    _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.8 * cm, bottomMargin=2 * cm,
        title="EVIDA 증거 정리 보고서",
    )
    styles = _get_styles()
    story = []
    story += _build_page1(case, len(selected), styles)
    story.append(PageBreak())
    story += _build_list_table(selected, meta, styles)
    for i, c in enumerate(selected):
        story.append(PageBreak())
        story += _build_evidence_page(c, i + 1, meta, styles)
    if meta.get("images"):
        story.append(PageBreak())
        story += _build_attachments(meta["images"], styles)
    story.append(PageBreak())
    story += _build_conclusion(selected, meta, styles)

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# 테스트
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    def _count_pages(data: bytes) -> int:
        try:
            from pypdf import PdfReader
            return len(PdfReader(io.BytesIO(data)).pages)
        except Exception:
            pass
        try:
            from PyPDF2 import PdfReader
            return len(PdfReader(io.BytesIO(data)).pages)
        except Exception:
            pass
        return len(re.findall(rb"/Type\s*/Page[^s]", data))

    def _make_comment(i, text, time_s="2024-05-01T12:00:00Z", author="작성자"):
        return dict(id=f"c{i}", author=author, channel=f"UC{i:04d}", cid=f"cid{i}",
                    text=text, time=time_s, link=f"https://youtube.com/watch?v=abc&lc=c{i}",
                    label="욕설", severity=2, category="모욕", reason="욕설 표현 포함",
                    law="모욕죄(형법 제311조) 의심", ai=0.82, gem="문맥상 모욕적 표현으로 보임",
                    statute="형법 제311조", target="", memo="")

    meta = dict(src="youtube", url="https://youtube.com/watch?v=abc",
                collected_at="2024-05-01T13:00:00Z", sha256="deadbeef" * 8, total=50, images=[])
    case = dict(title="", platform="YouTube", period="2024.04 ~ 2024.05", story="", harm="", note="")

    emoji_text = "이 영상 진짜 😡🤬 어이없네 ㅋㅋㅋ 🤡 완전 쓰레기같음"
    long_text = "가나다라" * 250  # 1000자
    blank_comment = dict(id="c_blank", author="", channel="", cid="", text="내용만 있음",
                          time="", link="", label="애매", severity=1, category="", reason="",
                          law="", statute="", ai=None, gem="", target="", memo="")

    tests = {
        "1건": [_make_comment(1, emoji_text)],
        "3건": [_make_comment(1, emoji_text), _make_comment(2, long_text), blank_comment],
        "20건": [_make_comment(i, f"테스트 댓글 {i} 😀") for i in range(1, 21)],
    }

    for name, rows in tests.items():
        try:
            pdf_bytes = make_pdf(rows, meta, case)
            print(f"[{name}] 성공 - 쪽수: {_count_pages(pdf_bytes)}, 크기: {len(pdf_bytes)} bytes")
        except Exception as e:
            print(f"[{name}] 실패 - {e}")

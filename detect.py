"""
EVIDA - detect.py
AI 악플 분석 및 증거자료 생성 서비스의 분류 모듈.
규칙 기반(욕설/비속어/인신공격/비난/위협/인신공격/혐오/성적/문맥) + 선택적 학습형 AI(ML) 보조.
streamlit을 import하지 않는다. (캐시는 app.py 책임)
"""

import re
import io
import hashlib
import unicodedata

# =========================================================================
# 0. 기본 유틸 (한글 자모 처리)
# =========================================================================

HANGUL_BASE = 0xAC00
HANGUL_LAST = 0xD7A3
CHOSUNG = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNGSUNG = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONGSUNG = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")

CONSONANT_JAMO = set("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")


def is_hangul_syllable(ch):
    return bool(ch) and HANGUL_BASE <= ord(ch) <= HANGUL_LAST


def decompose(ch):
    """완성형 한글 1글자 -> (초성,중성,종성) / 아니면 None"""
    if not is_hangul_syllable(ch):
        return None
    code = ord(ch) - HANGUL_BASE
    cho = code // (21 * 28)
    jung = (code % (21 * 28)) // 28
    jong = code % 28
    return CHOSUNG[cho], JUNGSUNG[jung], JONGSUNG[jong]


def compose(cho, jung, jong=""):
    try:
        ci = CHOSUNG.index(cho)
        ji = JUNGSUNG.index(jung)
        ki = JONGSUNG.index(jong) if jong in JONGSUNG else 0
    except ValueError:
        return None
    return chr(HANGUL_BASE + (ci * 21 + ji) * 28 + ki)


# =========================================================================
# 1. 전처리 (검사용 사본에만 적용, 원문 text는 보존)
# =========================================================================

def _collapse_repeats(s):
    """같은 글자 3번 이상 -> 1번"""
    return re.sub(r'(.)\1{2,}', r'\1', s)


def _stretch_merge(s):
    """늘여쓰기 복원:
    - 받침 없는 글자 뒤 'ㅇ+같은 모음'글자가 오면 지움 (씨이이발 -> 씨발 : 이미 collapse로 커버되지만
      '씨'+'이'(받침없음, 모음 다름) 패턴도 처리)
    - 받침 있는 글자 뒤 같은 글자(받침없이 반복)가 오면 합쳐서 받침을 만듦 (병시이인->병신)
    """
    chars = list(s)
    out = []
    i = 0
    while i < len(chars):
        ch = chars[i]
        d = decompose(ch)
        if d:
            cho, jung, jong = d
            if jong == "":
                # 받침 없는 글자 뒤 'ㅇ'+같은 모음(받침 없음) 글자 반복 -> 삭제 (시이이발 -> 시발, 씨이이이이이발 -> 씨발)
                # 종성이 있는 글자(예: '인')는 뒤의 합성 로직이 처리하도록 여기서 멈춘다.
                j = i + 1
                while j < len(chars):
                    d2 = decompose(chars[j])
                    if d2 and d2[0] == 'ㅇ' and d2[1] == jung and d2[2] == "":
                        j += 1
                        continue
                    break
                if j > i + 1:
                    out.append(ch)
                    i = j
                    continue
            # 받침 없는 글자 뒤, 받침없는 같은 자/모 글자가 연속되며 결과적으로 받침을 만드는 경우
            # 병시이인 -> 병 + 시 + 이 + 인 : '시'(받침없음) 다음 '이'(ㅇ+ㅣ, 받침없음) 다음 '인'(ㅇ+ㅣ+ㄴ)
            # => '시' 뒤 ㅇ+같은모음 글자들을 지우고 마지막에 종성이 있는 'ㅇ+같은모음+종성' 글자가 오면
            #    그 종성을 '시'에 붙여 '신'으로 합성
            if jong == "":
                j = i + 1
                skipped = 0
                while j < len(chars):
                    d2 = decompose(chars[j])
                    if d2 and d2[0] == 'ㅇ' and d2[1] == jung and d2[2] == "":
                        j += 1
                        skipped += 1
                        continue
                    break
                if j < len(chars):
                    d3 = decompose(chars[j])
                    if d3 and d3[0] == 'ㅇ' and d3[1] == jung and d3[2] != "" and skipped >= 0 and j > i:
                        merged = compose(cho, jung, d3[2])
                        if merged:
                            out.append(merged)
                            i = j + 1
                            continue
        out.append(ch)
        i += 1
    return "".join(out)


_NUM_WORD_MAP = [
    (re.compile(r'(?<!\d)18\s*(놈|년|새)'), lambda m: "씨발" + m.group(1)),
    (re.compile(r'(?<!\d)10\s*새'), lambda m: "씹새"),
]


def _number_sub(s):
    for pat, repl in _NUM_WORD_MAP:
        s = pat.sub(repl, s)
    return s


ROMAN_DICT = {
    "sibal": "시발", "ssibal": "씨발", "c bal": "씨발", "byungsin": "병신",
    "gae": "개", "sae": "새", "kki": "끼", "ji": "지", "ral": "랄",
}

# 영타(두벌식) -> 한글 오타 복원용 자판 매핑
_EN2KO_JAMO = {
    'q': 'ㅂ', 'w': 'ㅈ', 'e': 'ㄷ', 'r': 'ㄱ', 't': 'ㅅ', 'y': 'ㅛ', 'u': 'ㅕ',
    'i': 'ㅑ', 'o': 'ㅐ', 'p': 'ㅔ', 'a': 'ㅁ', 's': 'ㄴ', 'd': 'ㅇ', 'f': 'ㄹ',
    'g': 'ㅎ', 'h': 'ㅗ', 'j': 'ㅓ', 'k': 'ㅏ', 'l': 'ㅣ', 'z': 'ㅋ', 'x': 'ㅌ',
    'c': 'ㅊ', 'v': 'ㅍ', 'b': 'ㅠ', 'n': 'ㅜ', 'm': 'ㅡ',
    'Q': 'ㅃ', 'W': 'ㅉ', 'E': 'ㄸ', 'R': 'ㄲ', 'T': 'ㅆ', 'O': 'ㅒ', 'P': 'ㅖ',
}


def _jamo_seq_to_syllables(jamo_list):
    """자모 리스트를 한글 음절들로 조합 시도. 실패하면 None 반환."""
    out = []
    i = 0
    n = len(jamo_list)
    while i < n:
        cho = jamo_list[i]
        if cho not in CHOSUNG:
            return None
        if i + 1 >= n or jamo_list[i + 1] not in JUNGSUNG:
            return None
        jung = jamo_list[i + 1]
        jong = ""
        if i + 2 < n and jamo_list[i + 2] in CONSONANT_JAMO:
            # 종성 뒤가 다시 초성+중성 조합이 가능한지 확인(아니면 종성으로 소비)
            if i + 3 < n and jamo_list[i + 3] in JUNGSUNG and jamo_list[i + 2] in CHOSUNG:
                jong = ""
            else:
                cand = jamo_list[i + 2]
                if cand in JONGSUNG:
                    jong = cand
        syll = compose(cho, jung, jong)
        if not syll:
            return None
        out.append(syll)
        i += 3 if jong else 2
    return "".join(out)


_SI_BAL_PREFIX = re.compile(r'(씨|시)[ㅇㅋㅎ]*bal\b', re.IGNORECASE)


def _restore_english_blocks(s):
    """영문 덩어리를 한글 욕설로 복원 시도. 로마자 사전(2단어 결합 포함) 우선, 그다음 영타 변환."""

    def restore_token(tok):
        low = tok.lower()
        if low in ROMAN_DICT:
            return ROMAN_DICT[low]
        jamos = [_EN2KO_JAMO.get(c) for c in tok]
        if all(jamos):
            syl = _jamo_seq_to_syllables(jamos)
            if syl:
                return syl
        return None  # 복원 실패

    # 영어 비율 체크: 영어 단어 4개 이상 + 한글 10% 이하인 문장은 복원하지 않음
    words = re.findall(r'[A-Za-z]+', s)
    hangul_count = sum(1 for c in s if is_hangul_syllable(c))
    total_letters = hangul_count + sum(len(w) for w in words)
    if len(words) >= 4 and total_letters > 0 and hangul_count / total_letters <= 0.10:
        return s

    # 1) 한글 글자 바로 뒤 로마자 'bal'류가 붙어 '시/씨' + bal 조합을 이루는 경우 먼저 처리
    s = _SI_BAL_PREFIX.sub(lambda m: ("씨" if m.group(1) == "씨" else "시") + "발", s)

    # 2) 영문 1~2단어 덩어리를 통째로 복원 시도 (2단어 우선, 실패하면 1단어)
    out = []
    pos = 0
    for m in re.finditer(r'[A-Za-z]+(?:\s+[A-Za-z]+)?', s):
        out.append(s[pos:m.start()])
        chunk = m.group(0)
        restored = restore_token(chunk.replace(" ", ""))
        if restored is None and " " in chunk:
            # 2단어 결합 실패 시 단어 단위로 각각 시도
            parts = chunk.split()
            r0 = restore_token(parts[0])
            r1 = restore_token(parts[1]) if len(parts) > 1 else None
            if r0 or r1:
                restored = (r0 or parts[0]) + (r1 or (" " + parts[1] if len(parts) > 1 else ""))
        out.append(restored if restored is not None else chunk)
        pos = m.end()
    out.append(s[pos:])
    return "".join(out)


_PRONUNCIATION_CORE9 = ["시발", "병신", "븅신", "지랄", "염병", "개새끼", "니애미", "틀딱", "엠창"]


def _normalize_pronunciation(s, already_hit):
    """발음 정규화(보조): 된소리/거센소리->예사소리, ㅢㅟ->ㅣ, ㅐ->ㅔ 등.
    오탐 방지를 위해 핵심 9단어 검사용으로만, 다른 키워드가 하나도 안 걸렸을 때만 적용."""
    if already_hit:
        return s
    chars = list(s)
    out = []
    SOFTEN = {'ㄲ': 'ㄱ', 'ㄸ': 'ㄷ', 'ㅃ': 'ㅂ', 'ㅆ': 'ㅅ', 'ㅉ': 'ㅈ',
              'ㅋ': 'ㄱ', 'ㅌ': 'ㄷ', 'ㅍ': 'ㅂ', 'ㅊ': 'ㅈ'}
    for ch in chars:
        d = decompose(ch)
        if d:
            cho, jung, jong = d
            cho2 = SOFTEN.get(cho, cho)
            if jung in ('ㅢ', 'ㅟ'):
                jung = 'ㅣ'
            elif jung == 'ㅐ':
                jung = 'ㅔ'
            new = compose(cho2, jung, jong)
            out.append(new if new else ch)
        else:
            out.append(ch)
    return "".join(out)


def preprocess_for_check(text):
    s = text
    s = _collapse_repeats(s)
    s = _stretch_merge(s)
    s = _number_sub(s)
    s = _restore_english_blocks(s)
    return s


# =========================================================================
# 2. 키워드 사전
# =========================================================================

KEYWORDS = {
    "욕설": (3, [
        "시발", "씨발", "ㅅㅂ", "ㅆㅂ", "씨바", "씨팔", "시팔", "좆", "ㅈ같", "x같",
        "개새끼", "새끼", "ㅅㄲ", "병신", "ㅂㅅ", "ㅄ", "븅신", "지랄", "ㅈㄹ", "염병",
        "썅", "엠창", "느금", "ㄴㄱㅁ", "니애미", "애미", "애비", "18놈", "씹새",
        "장애냐", "고아새끼", "fuck", "shit", "bitch", "asshole",
    ]),
    "비속어": (1, ["존나", "졸라", "ㅈㄴ", "개같", "뒤진다", "뒤질"]),
    "비난": (1, [
        "악마", "꼴보기", "퉤", "ㅉㅉ", "존망", "토할", "와꾸", "뇬", "가증", "면상",
        "무지성", "발작버튼", "누칼협", "알빠노", "긁혔", "뇌절", "벌레같", "관종",
        "ㅗㅗ", "ㅁㅊ", "씹덕", "🖕",
    ]),
    "위협": (3, ["죽어라", "죽으세요", "죽어버려", "뒤져라", "뒤지세요", "디져", "자살해", "죽여버", "찾아간다", "패버"]),
    "인신공격": (2, [
        "미친놈", "미친년", "또라이", "돌아이", "멍청", "찐따", "한심", "쓰레기", "못생",
        "정신병자", "싸이코패스", "양아치", "인간같지", "인간이냐", "금수", "모자란",
        "머저리", "꽃뱀", "맞을짓", "피해자코스프레", "자작극", "꺼지세요", "닥치세요",
        "돼지같", "오크녀", "개저씨", "빻았", "역겹", "역겨", "꺼져", "닥쳐", "ㄲㅈ",
        "ㄷㅊ", "상태봐라", "꼬라지", "주제에", "얼굴값", "꼴값", "능지", "뇌빼고",
        "쿨찐", "방구석여포", "호소인", "idiot", "stupid", "moron", "loser",
    ]),
    "혐오": (3, [
        "한남", "한녀", "김치녀", "틀딱", "급식충", "잼민", "맘충", "짱깨", "쪽바리",
        "스윗한남", "퐁퐁남", "설거지론", "영포티", "오팔륙", "군캉스",
    ]),
    "성적": (3, ["따먹", "몸매보", "ㅗㅜㅑ", "눈요기", "육덕", "헤응", "스폰녀", "오피녀", "조건만남"]),
}

CHUNG_EXCEPT = {"대충", "보충", "확충", "곤충", "해충", "유충", "충분", "충격", "충전", "충돌"}
HANNAM_EXCEPT_SUFFIX = ("동", "대", "자", "쪽")

FALSE_POSITIVE_EXCEPTIONS = [
    "시발점", "시발역", "시발택시", "병신년", "병신정변", "애비뉴", "썅썅바",
    "금수저", "금수강산", "능지처참", "장애물", "정신병원", "쓰레기통", "분리수거", "쓰레기 분리수거",
    "쓰레기 봉투", "쓰레기봉투", "새끼 고양이", "새끼고양이", "새끼 강아지", "새끼강아지",
    "새끼 손가락", "새끼손가락", "새끼줄", "새끼를 낳", "주제에 대해", "지랄발광 17세",
]
# (딸기/사과/과일) 따먹, (불/화면/전원)이 꺼져, (위기/위험/겨울)이 닥쳐, (잠/시간/돈)이 모자란
FALSE_POSITIVE_PATTERNS = [
    re.compile(r'(딸기|사과|과일)\s*따먹'),
    re.compile(r'(불|화면|전원)이?\s*꺼져'),
    re.compile(r'(위기|위험|겨울)(이|가)?\s*닥쳐'),
    re.compile(r'(잠|시간|돈)(이|가)?\s*모자란'),
]

SEP_CLASS = r'[\sㅇㅋㅎㅡ0-9!-/:-@\[\]^_`{|}~]*'


def _build_kr_pattern(keyword):
    parts = [re.escape(c) for c in keyword]
    return SEP_CLASS.join(parts)


_PATTERN_CACHE = {}


def _get_compiled(keyword):
    if keyword in _PATTERN_CACHE:
        return _PATTERN_CACHE[keyword]
    if re.fullmatch(r'[A-Za-z]+', keyword):
        pat = re.compile(r'\b' + re.escape(keyword), re.IGNORECASE)
    else:
        pat = re.compile(_build_kr_pattern(keyword))
    _PATTERN_CACHE[keyword] = pat
    return pat


def _is_consonant_jamo(ch):
    return ch in CONSONANT_JAMO


def _in_long_consonant_run(s, start, end):
    """매치 구간이 '초성(ㅋㅎ 제외) 6개 이상 연속' 구간 안에 있는지 확인"""
    i = start
    while i > 0 and _is_consonant_jamo(s[i - 1]):
        i -= 1
    j = end
    while j < len(s) and _is_consonant_jamo(s[j]):
        j += 1
    run = s[i:j]
    core_run = [c for c in run if c not in ("ㅋ", "ㅎ")]
    return len(core_run) >= 6


def _touches_hangul_border(s, start, end, used_sep):
    if not used_sep:
        return False
    before_ok = start == 0 or not is_hangul_syllable(s[start - 1])
    after_ok = end >= len(s) or not is_hangul_syllable(s[end])
    return not (before_ok and after_ok)


def find_keyword_hits(check_text):
    """반환: [(category, severity, keyword, start, end), ...]"""
    hits = []
    for cat, (sev, words) in KEYWORDS.items():
        for kw in words:
            if kw == "한남" :
                for m in _get_compiled(kw).finditer(check_text):
                    end = m.end()
                    if end < len(check_text) and check_text[end] in HANNAM_EXCEPT_SUFFIX:
                        continue
                    _add_hit(hits, check_text, cat, sev, kw, m)
                continue
            for m in _get_compiled(kw).finditer(check_text):
                _add_hit(hits, check_text, cat, sev, kw, m)
    # 단어 끝 "~충" (예외 제외)
    for m in re.finditer(r'[가-힣]충', check_text):
        word = m.group(0)
        if word in CHUNG_EXCEPT:
            continue
        hits.append(("혐오", 3, word, m.start(), m.end()))
    return hits


def _add_hit(hits, s, cat, sev, kw, m):
    start, end = m.start(), m.end()
    matched_text = m.group(0)
    is_kr = not re.fullmatch(r'[A-Za-z]+', kw)
    used_sep = is_kr and len(matched_text) != len(kw)
    if used_sep and _touches_hangul_border(s, start, end, used_sep):
        return
    if re.fullmatch(r'[ㄱ-ㅎ]+', kw) and kw not in ("ㅗㅗ", "ㅗㅜㅑ") and _in_long_consonant_run(s, start, end):
        return
    hits.append((cat, sev, kw, start, end))


def strip_false_positives(s):
    for exc in FALSE_POSITIVE_EXCEPTIONS:
        s = s.replace(exc, " " * len(exc))
    for pat in FALSE_POSITIVE_PATTERNS:
        s = pat.sub(lambda m: " " * len(m.group(0)), s)
    return s


# =========================================================================
# 3. 문맥 규칙
# =========================================================================

GROUP_WORDS = ["성별", "나이대", "국적", "집단", "세대", "여자", "남자", "지역", "출신",
               "외국인", "장애", "노인", "전라", "경상", "충청", "강원", "제주"]
GROUP_GENERALIZE = ["과학이", "걸러야", "지능", "미개", "종특", "원래 그렇", "일반인이랑 다",
                     "수준 보", "통계로 증명", "하는 짓", "믿을 수 없", "생각이 없",
                     "내보내", "뻔하", "모두 같은", "다 똑같"]

SEXUAL_BODY = ["몸매", "핏이", "가슴", "엉덩", "허벅지", "다리", "골반", "몸 라인", "상의", "하의", "치마", "옷이"]
SEXUAL_GAZE = ["꽉 차", "터질", "눈이 감", "눈이 가", "눈 돌아", "꼴리", "군침", "만지고", "벗기"]
SEXUAL_GAZE_YAHAE_CTX = ["야해", "야하", "야한"]

OBJECTIFY_PARTS = ["몸매", "부위", "옷차림", "외모", "가슴", "엉덩", "허벅지"]
OBJECTIFY_TAIL = ["만 보", "눈이 가", "눈에 들어", "시선을 끌", "야하게", "성적인", "농담거리"]
OBJECTIFY_PARTS_EXTRA = ["몸매", "옷차림"]

POLITE_DEROGATION = ["수준 낮", "수준 이하", "수준 보니", "무식", "자격도 없", "자격 없", "답이 없",
                      "부끄럽지 않", "부끄러운 줄", "아는 척", "이해도 없", "이해력 없",
                      "생각이라는 걸", "생각이 없", "생각이 하나", "자체가 문제", "저급",
                      "쓸모 없", "어리석"]

THREAT_LOCATION = ["어디 사는지", "사는 곳", "집 앞", "학교 앞", "회사 앞", "출퇴근"]
THREAT_WARNING = ["조심해", "다 안다", "알고 있으니", "기다리면 되", "찾아가서"]
THREAT_ALONE = ["가만 두지", "가만두지", "가만 안 둬", "가만안둬", "가만두지 않겠", "가만 두지 않겠",
                "두고 보자", "어떻게 되는지 보자", "찾아가서", "알게 해줄게"]
TARGET_WORDS = ["you", "너", "니", "넌", "널", "네가", "님", "당신", "얘", "쟤", "니들", "이 새끼", "이 놈"]
TARGET_FALSE_POSITIVES = ["너무", "넌지", "니은", "니트"]


def _has_target(text):
    masked = text
    for fp in TARGET_FALSE_POSITIVES:
        masked = masked.replace(fp, " " * len(fp))
    return _any_in(TARGET_WORDS, masked)

DEFAME_WORDS = ["갑질", "사기", "횡령", "탈세", "불륜", "전과", "범죄자", "폭행", "마약",
                "학폭", "뒷광고", "표절", "조작", "주작", "숨겼", "빼돌", "소문", "의혹",
                "했대", "라던데", "카더라"]
DEFAME_QUOTE = ["다는 글", "다는 댓글", "다는 말", "다는 얘기", "다는 주장", "다고 글",
                "다고 댓글", "다고 말", "다고 얘기", "다고 주장", "라는 글", "라는 댓글",
                "라는 말", "라는 얘기", "라는 주장"]
GUESS_MARKERS = ["것 같", "듯", "?"]

PHONE_RE = re.compile(r'01\d-\d{3,4}-\d{4}')
ADDR_RE = re.compile(r'\d{3,4}\s*동\s*\d{3,4}\s*호')
SCHOOL_RE = re.compile(r'(학교|고등학교|중학교|초등학교|대학교)\s*\S{0,6}(다니|재학|학년)')

NO_TARGET_QUOTE = ["라고 했", "라고 쓴", "라는 말", "라는 댓글", "신고했", "무슨 뜻"]
SELF_DEPRECATE = ["나", "내", "저", "제", "내 자신"]
PRAISE_WORDS = ["지린다", "찢었", "미쳤다", "쩐다", "명곡", "띵곡", "소름", "역대급", "천재",
                "레전드", "개좋", "개쩔", "맛있", "웃기", "웃겨", "재밌", "귀엽", "예쁘",
                "최고", "대박", "amazing", "love", "best"]
EXCLAMATION_ONLY = {"시발", "씨발", "ㅅㅂ", "ㅆㅂ", "존나", "졸라", "ㅈㄴ", "개같", "좆", "ㅈㄹ", "지랄", "fuck", "shit"}
SITUATION_WORDS = ["날씨", "게임", "버스", "편집", "음질", "광고", "서버", "회사", "시험", "자막"]


def _any_in(words, text):
    return any(w in text for w in words)


LAW_MAP = {
    "욕설": ("모욕 의심", "형법 제311조(모욕)"),
    "비속어": ("모욕 의심", "형법 제311조(모욕)"),
    "인신공격": ("모욕 의심", "형법 제311조(모욕)"),
    "비난": ("모욕 의심", "형법 제311조(모욕)"),
    "위협": ("협박 의심", "형법 제283조(협박)"),
    "성적": ("성희롱·모욕 의심", "형법 제311조"),
    "명예훼손": ("명예훼손 검토", "정보통신망법 제70조(사실 1항·허위 2항)"),
    "혐오": ("집단 비하(개인 특정 어려우면 고소 어려움)", "개인이 특정되면 형법 제311조"),
    "신상노출": ("신상 노출 의심(즉시 삭제 요청 권장)", "플랫폼 신고·삭제 요청"),
    "AI 판단": ("검토 필요", "검토 필요"),
}


def classify(text):
    """댓글 1개 텍스트를 분석해 dict(label, severity, category, reason, law, statute) 반환.
    원문 text는 이 함수 내부에서 수정하지 않는다."""
    original = text or ""
    check = preprocess_for_check(original)
    check_stripped = strip_false_positives(check)

    hits = find_keyword_hits(check_stripped)
    if not hits:
        hits = _normalize_pronunciation_hits(check_stripped)

    categories = {}  # cat -> severity
    reasons = []
    for cat, sev, kw, s, e in hits:
        categories[cat] = max(categories.get(cat, 0), sev)

    # ---- 문맥 규칙 ----
    if _any_in(GROUP_WORDS, check_stripped) and _any_in(GROUP_GENERALIZE, check_stripped):
        categories["혐오"] = max(categories.get("혐오", 0), 1)
        reasons.append("집단 비하 의심(일반화 표현)")
    if re.search(r'[가-힣]특(?:\s|$)', check_stripped) and not check_stripped.strip().endswith("특"):
        pass

    if _any_in(SEXUAL_BODY, check_stripped) and (_any_in(SEXUAL_GAZE, check_stripped) or
            re.search(r'(^|\s|너무|넘|좀|개)(야해|야하|야한)', check_stripped)):
        if "야하게' 봐야하는" not in check_stripped:
            categories["성적"] = max(categories.get("성적", 0), 3)
            reasons.append("성희롱 의심(신체 묘사+성적 시선)")

    for part in OBJECTIFY_PARTS + OBJECTIFY_PARTS_EXTRA:
        idx = check_stripped.find(part)
        if idx >= 0:
            window = check_stripped[idx: idx + len(part) + 30]
            if _any_in(OBJECTIFY_TAIL, window):
                categories["성적"] = max(categories.get("성적", 0), 1)
                reasons.append("성적 대상화 의심")
                break
    if "성적" not in categories and "야하게" in check_stripped and _any_in(["찍", "촬영", "카메라"], check_stripped):
        categories["성적"] = max(categories.get("성적", 0), 1)
        reasons.append("성적 대상화 의심(촬영 각도)")

    if _any_in(POLITE_DEROGATION, check_stripped):
        categories["인신공격"] = max(categories.get("인신공격", 0), 1)
        reasons.append("정중한 비하 표현")

    has_location = _any_in(THREAT_LOCATION, check_stripped)
    has_warning = _any_in(THREAT_WARNING, check_stripped)
    has_alone = _any_in(THREAT_ALONE, check_stripped)
    has_target = _has_target(check_stripped)
    if (has_location and has_warning) or has_alone:
        categories["위협"] = max(categories.get("위협", 0), 2)
        reasons.append("위협 의심(거주지/동선+경고 또는 경고성 표현)")
    elif has_warning and has_target:
        categories["위협"] = max(categories.get("위협", 0), 1)
        reasons.append("경고성 위협 의심(대상 지목)")

    defame_trigger = _any_in(DEFAME_WORDS, check_stripped) or _any_in(DEFAME_QUOTE, check_stripped)
    if defame_trigger:
        categories["명예훼손"] = max(categories.get("명예훼손", 0), 1)
        if _any_in(GUESS_MARKERS, check_stripped):
            reasons.append("명예훼손 검토(추측·의견)")
        else:
            reasons.append("명예훼손 검토(단정)")

    if PHONE_RE.search(original) or ADDR_RE.search(original):
        categories["신상노출"] = max(categories.get("신상노출", 0), 3)
        reasons.append("신상 노출 의심")
    elif SCHOOL_RE.search(original):
        categories["신상노출"] = max(categories.get("신상노출", 0), 1)
        reasons.append("신상 정보 암시")

    # ---- 완화 규칙 (위협/성적/명예훼손/신상노출 제외) ----
    EXEMPT = {"위협", "성적", "명예훼손", "신상노출"}
    mitigatable = {c: v for c, v in categories.items() if c not in EXEMPT}
    if mitigatable:
        hit_keywords = {kw for (cat, sev, kw, s, e) in hits if cat not in EXEMPT}
        if not has_target:
            if hit_keywords and hit_keywords.issubset(EXCLAMATION_ONLY) and _any_in(PRAISE_WORDS, check_stripped):
                for c in list(categories.keys()):
                    if c not in EXEMPT:
                        del categories[c]
                reasons.append("칭찬·감탄 속 욕설(대상 없음)")
            else:
                downgrade_reason = None
                if _any_in(NO_TARGET_QUOTE, check_stripped) or check_stripped.strip().startswith("??:"):
                    downgrade_reason = "인용·신고·뜻 질문"
                elif hit_keywords and hit_keywords.issubset(EXCLAMATION_ONLY):
                    downgrade_reason = "감탄사형 욕설(대상 없음)"
                elif _any_in(SELF_DEPRECATE, check_stripped):
                    downgrade_reason = "자기 비하" + ("·칭찬" if _any_in(PRAISE_WORDS, check_stripped) else "")
                elif _any_in(SITUATION_WORDS, check_stripped):
                    downgrade_reason = "사물·상황에 대한 표현(대상 없음)"
                if downgrade_reason:
                    for c in list(categories.keys()):
                        if c not in EXEMPT and categories[c] > 1:
                            categories[c] = 1
                    reasons.append(f"대상 불명확: {downgrade_reason}")

    if not categories:
        return dict(label="정상", severity=0, category="", reason="키워드 미검출", law="", statute="")

    severity = max(categories.values())
    cat_list = sorted(categories.keys(), key=lambda c: -categories[c])
    category_str = ",".join(cat_list)
    laws, statutes = [], []
    for c in cat_list:
        law, statute = LAW_MAP.get(c, ("검토 필요", "검토 필요"))
        if law not in laws:
            laws.append(law)
        if statute not in statutes:
            statutes.append(statute)
    reason_str = "; ".join(reasons) if reasons else f"키워드 검출({category_str})"
    label = "악플" if severity >= 1 else "정상"
    return dict(
        label=label,
        severity=severity,
        category=category_str,
        reason=reason_str,
        law=",".join(laws),
        statute=",".join(statutes),
    )


def _normalize_pronunciation_hits(check_stripped):
    norm = _normalize_pronunciation(check_stripped, already_hit=False)
    hits = []
    for word in _PRONUNCIATION_CORE9:
        for m in _get_compiled(word).finditer(norm):
            used_sep = len(m.group(0)) != len(word)
            if _touches_hangul_border(norm, m.start(), m.end(), used_sep):
                continue
            cat = next((c for c, (sev, ws) in KEYWORDS.items() if word in ws), "욕설")
            sev = KEYWORDS.get(cat, (3, []))[0]
            hits.append((cat, sev, word, m.start(), m.end()))
    return hits


# =========================================================================
# 4. 학습형 AI (선택)
# =========================================================================

def train_model():
    """unsmile / K-MHaS 데이터셋으로 TF-IDF + LogisticRegression 학습. 실패 시 None."""
    try:
        import pandas as pd
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        df1 = pd.read_csv(
            "https://raw.githubusercontent.com/smilegate-ai/korean_unsmile_dataset/main/unsmile_train_v1.0.tsv",
            sep="\t",
        )
        texts1 = df1["문장"].astype(str).tolist()
        labels1 = (df1["clean"].astype(int) == 0).astype(int).tolist()

        df2 = pd.read_csv(
            "https://raw.githubusercontent.com/adlnlp/K-MHaS/main/data/kmhas_train.txt",
            sep="\t", quoting=3, header=None, names=["document", "label"],
        )
        texts2 = df2["document"].astype(str).str.strip('"').tolist()
        labels2 = (df2["label"].astype(str) != "8").astype(int).tolist()

        texts = texts1 + texts2
        labels = labels1 + labels2

        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 4), min_df=3,
                               sublinear_tf=True, max_features=300000)
        X = vec.fit_transform(texts)
        model = LogisticRegression(max_iter=3000, C=4, class_weight="balanced")
        model.fit(X, labels)
        return (vec, model)
    except Exception:
        return None


def apply_model(rows, model):
    """rows의 각 dict에 ai(0~100 정수) 추가/수정. 규칙상 정상인데 AI확률 높으면 악플로 재분류."""
    if not model:
        for r in rows:
            r["ai"] = r.get("ai", 0)
        return rows
    vec, clf = model
    texts = [r.get("text", "") for r in rows]
    try:
        X = vec.transform(texts)
        probs = clf.predict_proba(X)[:, 1]
    except Exception:
        probs = [0.0] * len(rows)
    for r, p in zip(rows, probs):
        ai_score = int(round(p * 100))
        r["ai"] = ai_score
        hangul_count = sum(1 for c in r.get("text", "") if is_hangul_syllable(c))
        jamo_noise = sum(1 for c in r.get("text", "") if c in CHOSUNG or c in JUNGSUNG)
        if r.get("label") in (None, "", "정상") and p >= 0.65 and hangul_count >= 2 and jamo_noise < hangul_count:
            r["label"] = "악플"
            r["severity"] = max(r.get("severity", 0) or 0, 1)
            r["category"] = (r.get("category") + ",AI 판단") if r.get("category") else "AI 판단"
            r["reason"] = (r.get("reason") + f"; AI 악플 확률 {ai_score}%") if r.get("reason") else f"AI 악플 확률 {ai_score}%"
    return rows


# =========================================================================
# 5. 피해자 태깅 / 검색
# =========================================================================

def tag_victim(rows, names):
    """names(이름/별명 리스트)이 댓글 text에 언급되면 target에 '✓ 이름' 표시."""
    names = [n for n in (names or []) if n]
    for r in rows:
        text = r.get("text", "")
        for name in names:
            if find_word(name, text):
                r["target"] = f"✓ {name}"
                break
        else:
            r.setdefault("target", "")
    return rows


def find_word(word, text):
    """끼워넣기·변형까지 찾는 검색 (화면 검색창용). (1)의 구분자 규칙 사용."""
    if not word or not text:
        return False
    check = preprocess_for_check(text)
    check = strip_false_positives(check)
    pat = re.compile(_build_kr_pattern(word)) if not re.fullmatch(r'[A-Za-z]+', word) \
        else re.compile(re.escape(word), re.IGNORECASE)
    for m in pat.finditer(check):
        used_sep = len(m.group(0)) != len(word)
        if _touches_hangul_border(check, m.start(), m.end(), used_sep):
            continue
        return True
    return False


# =========================================================================
# 6. 자가 테스트
# =========================================================================

_MUST_ABUSE = """tlqkf 진짜
qudtls
시ㅇㅇbal
c bal
sibal
ssibal 이게
씌발 뭐냐
븅씬아
ㄷㅊ 진짜
병1신
씨ㅋㅋ발
병 신 같네
x같네
꺼져라 관종아
너 같은 병신은 처음 봄
이 새끼 존나 웃기네
씨이이이이이발
병시이이인
10새야
18놈아
틀딱 소리
죽어라
뒤져라
fuck you
you stupid idiot
꺼지세요
닥치세요 좀
ㅄ
오크녀
개저씨 극혐
얼굴 빻았네
꽃뱀 아니냐
맞을 짓 했네
얘 010-1234-5678 번호임
OO아파트 103동 1202호 산대
관종충들
급식충
능지이슈 ㅋㅋ
누칼협?
알빠노
ㅗㅜㅑ
핏이 너무 야해서 몇 번을
오늘 옷 상의 쪽이 진짜 꽉 차 보이시네요
역시 그 성별 과학이네 ㅋㅋㅋ 지능 수준 잘 보고 갑니다
그 지역 사람들은 신기하게 사고방식 자체가 일반인이랑 다른 듯
직원 갑질하고 협박하고
에휴 댓글 상태봐라
ㅂㅅ아
너 ㅈㄹ 하지마
진짜 의상부터가 존나 동네머저리같네""".splitlines()

_MUST_NORMAL = """Hello MrBeast team, My name is Tania. I recently lost my job and the CCTV/security field.
Great video! Love from India
hello world
since 2020
This hit song is great
질병 신호가 왔다
그 애 비밀
한 녀석이 왔는데
이번 시 발표 좋았음
새끼 고양이 귀엽다
새끼줄 꼬는 법
소가 새끼를 낳았다
쓰레기 분리수거 영상
사발면 먹고싶다
칼로리 정보
재미있네요
시발점이 어디야
병신년 역사 공부
애비뉴 거리 산책
딸기 따먹기 체험
불이 꺼져서 무서웠어
위기가 닥쳐왔다
금수저 논란
잠이 모자란 하루
능지처참 역사
썅썅바 먹고싶다
보충 설명 감사해요
곤충 영상 좋아요
충분히 공감해요
한남동 맛집
독특하네요
특히 좋았어요
2018년에 찍은 영상
18세 이상 시청
10시에 만나요
좋아아아아
등을 긁었더니 시원
장애인 인식 개선 캠페인
고아원 봉사 다녀왔어요
스폰서 감사합니다
와 노래 지린다 ㅅㅂ
씨발 개쩐다 명곡
미드좀보지
닥치는 대로 먹었다
시바견 너무 귀여워
돼지고기 레시피
서랍 뒤져봐
나는 누가 못했고 잘했는지 봐야하는데 라인전
게임 질뻔한 거마냥 대충
ㄴ ㅇㄱ ㄱㅇㅈ ㅇ ㅎㅂ ㅈㅈㄹㅂㄹㄹ
나 인간 김인직 일 한번 저질러보리라
영상 잘 봤어요""".splitlines()

_MUST_NO_AUTOPICK = """누가 나한테 병신이라고 했어요 ㅠ
날씨 시발 너무 춥다
편집 쓰레기네
한심한 내 모습 ㅠ
존나 맛있다
아 씨발 이건 못참지;;
계절이 도대체 뭐야 ㅅㅂ ㅋㅋㅋ
병신이 무슨 뜻이에요?
??: 왜 못사게 하는데 개 미친새끼야
갑질 한 것 같은데?""".splitlines()

_TEAM50 = """T01\t정상\t편집이 조금 산만해서 중간에 보기 힘들었습니다.
T02\t정상\t배경음악 소리가 너무 커요. 다음 영상에서는 낮춰 주세요.
T03\t정상\t말씀하신 수치의 출처가 궁금합니다.
T04\t정상\t이 제품은 가격에 비해 성능이 아쉽네요.
T05\t정상\t최근 recently 올리신 영상은 조금 짧았어요.
T06\t정상\t사발면 먹으면서 봤는데 재밌었어요.
T07\t정상\t저는 그 주장에 동의하지 않습니다.
T08\t정상\t영상에서 인용된 "바보"라는 말의 맥락이 궁금해요.
T09\t정상\t설명 순서가 헷갈립니다. 예시가 더 있으면 좋겠습니다.
T10\t정상\t정정 공지를 올려 주시면 좋겠습니다.
T11\t인신공격\t말하는 수준을 보니 기본적인 이해도 없는 것 같네요.
T12\t인신공격\t저렇게 생각하는 사람이 있다는 게 참 한심합니다.
T13\t인신공격\t내용 말고 당신 자체가 문제입니다.
T14\t인신공격\t당신은 뭘 해도 답이 없을 것 같아요.
T15\t인신공격\t이 영상 만든 사람은 생각이라는 걸 하나요?
T16\t인신공격\t수준 낮은 사람이 아는 척하는 모습 보기 싫네요.
T17\t인신공격\t세상에 이렇게 무식한 사람이 있군요.
T18\t인신공격\t그렇게 사는 게 부끄럽지 않아요?
T19\t인신공격\t당신 같은 사람은 말할 자격도 없어 보여요.
T20\t위협\t어디 사는지 알고 있으니까 말 조심해.
T21\t위협\t밖에서 만나면 어떻게 되는지 보자.
T22\t위협\t계속 올리면 직접 찾아가서 따질 거야.
T23\t위협\t학교 앞에서 기다리면 되겠네.
T24\t위협\t너 출퇴근하는 길 다 안다.
T25\t위협\t다음 영상 올리면 가만두지 않겠어.
T26\t위협\t내가 누구인지 알게 해줄게. 조심해.
T27\t성적\t영상 내용보다 몸매만 계속 보게 되네요.
T28\t성적\t그 옷차림은 일부러 사람들의 시선을 끌려는 거죠?
T29\t성적\t얼굴보다 특정 부위에만 눈이 가네요.
T30\t성적\t내용은 안 들리고 몸매만 눈에 들어옵니다.
T31\t성적\t카메라 각도를 보니 일부러 야하게 찍은 것 같네요.
T32\t성적\t저 분 외모를 성적인 농담거리로 삼아도 되겠네요.
T33\t집단비하\t그 지역 출신은 전부 믿을 수 없다는 말이 맞네.
T34\t집단비하\t저 나이대 사람들은 원래 생각이 없지.
T35\t집단비하\t특정 국적 사람은 다 내보내야 해.
T36\t집단비하\t그 출신이면 수준이 뻔하죠.
T37\t집단비하\t그 집단 사람들은 모두 같은 문제를 일으켜.
T38\t사실주장\t저 사람이 후원금을 개인적으로 썼다는 소문이 있어요.
T39\t사실주장\t저 업체가 돈을 받고 후기 조작을 했다고 들었습니다.
T40\t사실주장\t방송에서 한 말이 사실이 아니라는 의혹이 있습니다.
T41\t사실주장\t저 사람은 과거에 표절했다는 글이 돌던데요.
T42\t사실주장\t이 상품의 인증이 조작됐다는 댓글을 봤습니다.
T43\t사실주장\t저 채널이 광고임을 일부러 숨겼다고 주장하는 사람이 있어요.
T44\t판단유보\t와 진짜 미쳤다 ㅋㅋ
T45\t판단유보\t너 정말 대단하다^^
T46\t판단유보\t오늘도 레전드네...
T47\t판단유보\t얘 또 시작이네.
T48\t판단유보\t친구가 저보고 "바보야"라고 했어요.
T49\t판단유보\t여기 사람들 진짜 이상하네?""".splitlines()


def _run_self_test():
    total = 0
    fail = 0
    failures = []

    for s in _MUST_ABUSE:
        total += 1
        r = classify(s)
        if r["label"] != "악플":
            fail += 1
            failures.append(("반드시 악플인데 정상 판정", s, r))

    for s in _MUST_NORMAL:
        total += 1
        r = classify(s)
        if r["label"] != "정상":
            fail += 1
            failures.append(("반드시 정상인데 악플 판정", s, r))

    for s in _MUST_NO_AUTOPICK:
        total += 1
        r = classify(s)
        if r["label"] == "악플" and r["severity"] >= 2:
            fail += 1
            failures.append(("자동선택 금지 위반(severity>=2)", s, r))

    for line in _TEAM50:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        _id, tag, sentence = parts
        total += 1
        r = classify(sentence)
        ok = True
        if tag == "정상":
            ok = r["label"] == "정상"
        elif tag == "판단유보":
            ok = True
        else:
            ok = r["label"] == "악플"
        if not ok:
            fail += 1
            failures.append((f"{_id}({tag}) 판정 오류", sentence, r))

    passed = total - fail
    rate = passed / total * 100 if total else 0
    print(f"=== detect.py 자가 테스트 결과: {passed}/{total} 통과 ({rate:.1f}%) ===")
    if failures:
        print(f"--- 실패 문장 {len(failures)}건 ---")
        for reason, sentence, result in failures:
            print(f"[{reason}] '{sentence}' -> {result}")


if __name__ == "__main__":
    _run_self_test()

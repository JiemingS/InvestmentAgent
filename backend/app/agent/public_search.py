import re
import unicodedata

WORDS = re.compile(r"[^\W_]+", re.UNICODE)
CLAUSES = re.compile(
    r"[,;!?\n，；？！。]|(?<=\.)\s+|\band\s+(?=(?:find|search|look\s+up|research|check|summarize)\b)",
    re.I,
)
PRIVATE = re.compile(
    r"\b(?:my|our|private\s+(?:balance|information|data|record\w*)|personal\s+(?:data|record\w*)|"
    r"account(?:\s+(?:number|id|balance))?|held|holdings|positions|cost\s+basis|unrealized|"
    r"portfolio|transaction\w*)\b"
    r"|\bi\s+(?:hold|own|bought|sold)\b"
    r"|\b\d+(?:\.\d+)?\s+(?:shares|units)\b|[$€£@]|https?://"
    r"|我的|我持有|我买|我卖|账户|账号|持仓|密码|密钥|交易记录|成本价|仓位|份额",
    re.I,
)
PRIVATE_NUMBER = re.compile(r"\d{5,}|\d[.,]\d")
SECRET = re.compile(r"\b(?:password|passcode|credential\w*|access\s+token|api[ -]?key|ssn|bearer|secret)\b|密码|密钥|令牌", re.I)
JOURNEY = re.compile(r"\b(?:my|our)\s+(?:investment|investing|trading)\s+(?:journey|history)\b|我的投资(?:历程|历史)", re.I)
MACRO = re.compile(r"\b(?:current|recent|latest)\s+(?:economic (?:environment|conditions|outlook)|macroeconomic (?:environment|conditions|outlook))\b|(?:当前|近期|最新)(?:宏观|经济环境)", re.I)
PUBLIC_MACRO_QUERY = "economic outlook inflation employment monetary policy"
HELPERS = {"official", "source", "sources", "report", "reports", "results", "latest", "update", "overview", "data",
           "top", "current", "breaking", "today", "recent", "global", "world", "international", "headlines"}
FILLER = {"the", "a", "an", "is", "was", "are", "did", "do", "does", "of", "in", "on", "and", "for",
          "find", "search", "look", "up", "tell", "explain", "give", "me", "please", "what", "who", "when", "about"}


def public_clauses(question: str) -> list[str]:
    """Keep private clauses out of the isolated query expansion call."""
    text = unicodedata.normalize("NFKC", question).casefold()
    if SECRET.search(text):
        return []
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return [
        clause.strip() for clause in CLAUSES.split(text)
        if clause.strip() and not PRIVATE.search(clause) and not PRIVATE_NUMBER.search(clause)
        and not JOURNEY.search(clause)
    ]


def terms_from_text(text: str) -> set[str]:
    return {
        word for word in WORDS.findall(unicodedata.normalize("NFKC", text).casefold())
        if len(word) <= 35 and (
            not any(char.isdigit() for char in word) or re.fullmatch(r"(?:19|20)\d{2}", word)
        )
    }


def public_terms(question: str) -> set[str]:
    return terms_from_text(" ".join(public_clauses(question)))


def query_words(proposed: str) -> list[str] | None:
    text = unicodedata.normalize("NFKC", proposed).casefold()
    if PRIVATE.search(text) or SECRET.search(text) or PRIVATE_NUMBER.search(text) or re.search(r"[^\w\s\-&’']", text):
        return None
    words = list(dict.fromkeys(WORDS.findall(text)))
    return words if 1 <= len(words) <= 14 else None


def query_signature(proposed: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", proposed).casefold()
    return tuple(sorted(set(WORDS.findall(text)) - FILLER - HELPERS))


def scoped_query(question: str, proposed: str, *, extra_terms: set[str] | None = None) -> str | None:
    if SECRET.search(unicodedata.normalize("NFKC", question)):
        return None
    words = query_words(proposed)
    terms = public_terms(question) | (extra_terms or set())
    if not words or set(words) - terms - HELPERS - FILLER:
        return None
    if not set(words) & (terms - HELPERS - FILLER):
        return None
    return " ".join(word for word in words if word not in FILLER)

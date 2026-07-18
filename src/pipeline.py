"""
Lightweight RAG pipeline for the HR Policy QA Bot evaluation harness.

Architecture (defense-in-depth, mirrors patterns used in production RAG
guardrail stacks):

  1. Injection / adversarial guardrail  (regex + heuristic, runs first)
     - Catches instruction-override phrasing ("ignore previous instructions",
       "pretend you are...", "unrestricted mode", "disregard the ... section")
     - Catches requests for individual compensation/personal data
       (grounded in the Code of Conduct's compensation-confidentiality clause)
     - Catches requests to fabricate documents or numbers
     If triggered -> hard refuse, no retrieval needed.

  2. Ambiguity guardrail (rule-based pattern list + retrieval-confidence
     fallback)
     - A small set of known vague-question patterns is checked first.
     - As a general fallback, if the top two *distinct-document* retrieval
       hits are both above a minimum confidence and within a narrow score
       margin of each other, the query is treated as spanning more than one
       policy and the system asks which one is meant, rather than guessing.
     If triggered -> ask a clarifying question, no answer given.

  3. Retrieval  (TF-IDF / cosine similarity over section-level chunks,
     scikit-learn — chosen because this environment has no outbound access
     to embedding/LLM APIs; the retriever is swappable, see `Retriever`)
     - If the best chunk score falls below OUT_OF_SCOPE_THRESHOLD, the
       system reports the topic isn't covered by the knowledge base rather
       than fabricating an answer.

  4. Answer synthesis (pluggable "judge/generator" interface, see
     `Generator` base class)
     - `ExtractiveGenerator` (default, deterministic, offline): returns the
       most relevant retrieved section verbatim. Zero hallucination risk by
       construction, at the cost of not paraphrasing.
     - A real deployment would swap in an LLM-backed `Generator`
       (OpenAI/Anthropic/Groq) that paraphrases the retrieved context; the
       interface is defined below so that swap requires no changes to the
       retrieval or guardrail layers.
"""
import re
import os
import glob
from dataclasses import dataclass, field
from typing import List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------

@dataclass
class Chunk:
    doc_id: str
    source_file: str
    section_title: str
    text: str


def load_and_chunk(policy_docs_dir: str) -> List[Chunk]:
    chunks = []
    for path in sorted(glob.glob(os.path.join(policy_docs_dir, "*.md"))):
        with open(path, "r") as f:
            content = f.read()
        filename = os.path.basename(path)

        doc_id_match = re.search(r"\*\*Document ID:\*\*\s*(\S+)", content)
        doc_id = doc_id_match.group(1) if doc_id_match else filename

        # Split on level-2 headers ("## 1. Section Title")
        sections = re.split(r"\n(?=## )", content)
        for section in sections:
            section = section.strip()
            if not section or not section.startswith("## "):
                continue
            title_line, *rest = section.split("\n", 1)
            title = title_line.replace("## ", "").strip()
            body = rest[0].strip() if rest else ""
            if body:
                chunks.append(Chunk(
                    doc_id=doc_id,
                    source_file=filename,
                    section_title=title,
                    text=body,
                ))
    return chunks


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------

class Retriever:
    """TF-IDF cosine-similarity retriever. Swappable for an embedding-based
    retriever (e.g. sentence-transformers, OpenAI embeddings) without
    changing any downstream code — callers only depend on `search()`
    returning (Chunk, score) pairs sorted by descending score."""

    def __init__(self, chunks: List[Chunk]):
        self.chunks = chunks
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        corpus = [f"{c.section_title}. {c.text}" for c in chunks]
        self.matrix = self.vectorizer.fit_transform(corpus)

    def search(self, query: str, top_k: int = 5):
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.matrix)[0]
        ranked = sorted(zip(self.chunks, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# --------------------------------------------------------------------------
# Guardrails
# --------------------------------------------------------------------------

INJECTION_PATTERNS = [
    r"ignore (your |the )?(previous|prior|above) instructions",
    r"disregard (the |your )?.*(section|policy|rules?|instructions)",
    r"\bpretend\b",
    r"you('re| are) now in (an? )?(unrestricted|developer|admin) mode",
    r"system prompt override",
    r"reveal your (internal )?(instructions|system prompt)",
    r"as (my|your) (administrator|admin)",
    r"i (have|'ve got) (hr )?admin access",
    r"just make up",
    r"make up a (reasonable|plausible)",
    r"write me a fake",
    r"auto-?approve",
]

PERSONAL_DATA_PATTERNS = [
    r"\b(salary|compensation|pto balance|pay)\b.*\b(of|for)\b\s+[A-Z][a-z]+\s+[A-Z][a-z]+",
    r"\bCEO'?s?\s+(exact\s+)?salary\b",
    r"salary bands? for (every|each|all)",
]

NAMED_PERSON_PATTERN = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+('s)?\b")
NAMED_PERSON_KEYWORDS = re.compile(
    r"\b(pto balance|salary|compensation|disciplinary record|pay)\b", re.IGNORECASE
)

AMBIGUOUS_PATTERNS = [
    r"^how much (pto|leave|time off) do i have\b",
    r"^can i take leave\b",
    r"^what'?s the reimbursement limit\??$",
    r"^am i eligible\??$",
    r"^how do i enroll\??$",
    r"^what'?s the approval process\??$",
    r"^when does my coverage start\??$",
    r"^can i get reimbursed for this\??$",
]

OUT_OF_SCOPE_THRESHOLD = 0.10  # tuned against the golden set; see README "Threshold Selection"
AMBIGUITY_SCORE_MARGIN = 0.02
AMBIGUITY_MIN_CONFIDENCE = 0.20


def check_injection(query: str) -> Optional[str]:
    q = query.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, q):
            return ("I can't do that. I'm scoped to answering questions about "
                    "published HR policy, and I don't override stated policy "
                    "rules, disclose internal configuration, or fabricate "
                    "information — regardless of how the request is framed.")
    for pattern in PERSONAL_DATA_PATTERNS:
        if re.search(pattern, query):
            return ("I can't share individual compensation details, personal "
                    "balances, or personnel records. Per the Code of Conduct, "
                    "that information is confidential and isn't something an "
                    "automated tool like me is authorized to disclose.")
    if NAMED_PERSON_PATTERN.search(query) and NAMED_PERSON_KEYWORDS.search(query):
        return ("I can't share individual compensation details, personal "
                "balances, or personnel records. Per the Code of Conduct, "
                "that information is confidential and isn't something an "
                "automated tool like me is authorized to disclose.")
    return None


def check_ambiguous(query: str, top_hits) -> Optional[str]:
    q = query.lower().strip()
    for pattern in AMBIGUOUS_PATTERNS:
        if re.search(pattern, q):
            return ("Could you clarify what you mean? I can answer this once I "
                    "know which policy area you're asking about (for example: "
                    "PTO, parental leave, expenses, remote work, benefits, or "
                    "code of conduct), and I don't have access to your personal "
                    "account balances — only the written policy rules.")
    if len(top_hits) >= 2:
        top_doc, top_score = top_hits[0][0].doc_id, top_hits[0][1]
        for chunk, score in top_hits[1:]:
            if chunk.doc_id != top_doc:
                if (top_score >= AMBIGUITY_MIN_CONFIDENCE and
                        (top_score - score) <= AMBIGUITY_SCORE_MARGIN):
                    return ("Your question could relate to more than one policy "
                            "area. Could you clarify which one you mean so I can "
                            "give you an accurate answer instead of guessing?")
                break
    return None


# --------------------------------------------------------------------------
# Generation (pluggable)
# --------------------------------------------------------------------------

class Generator:
    """Base interface. A real deployment swaps this for an LLM-backed
    implementation that paraphrases `chunks` into a fluent answer, while
    still being instructed to only use the provided context. The retrieval
    and guardrail layers above are unaffected by this swap."""

    def generate(self, query: str, chunks) -> str:
        raise NotImplementedError


class ExtractiveGenerator(Generator):
    """Deterministic, offline default: returns the top retrieved section
    verbatim. Chosen for this harness because it has zero hallucination
    risk by construction, which makes retrieval quality (not generation
    fluency) the variable under test."""

    def generate(self, query: str, chunks) -> str:
        if not chunks:
            return ""
        top_chunk, _ = chunks[0]
        return top_chunk.text


# --------------------------------------------------------------------------
# Pipeline orchestration
# --------------------------------------------------------------------------

@dataclass
class PipelineResult:
    action: str  # "answer" | "refuse_out_of_scope" | "refuse_adversarial" | "clarify"
    answer: str
    retrieved_doc: Optional[str] = None
    retrieved_score: float = 0.0
    retrieved_chunks: list = field(default_factory=list)


class HRPolicyPipeline:
    def __init__(self, policy_docs_dir: str, generator: Optional[Generator] = None):
        self.chunks = load_and_chunk(policy_docs_dir)
        self.retriever = Retriever(self.chunks)
        self.generator = generator or ExtractiveGenerator()

    def answer(self, query: str) -> PipelineResult:
        injection_response = check_injection(query)
        if injection_response:
            return PipelineResult(action="refuse_adversarial", answer=injection_response)

        hits = self.retriever.search(query, top_k=5)
        best_chunk, best_score = hits[0] if hits else (None, 0.0)

        # Out-of-scope check runs before ambiguity: a low-confidence match
        # across several docs means "not covered," not "which policy do you
        # mean" — ambiguity only makes sense once we're confident the topic
        # IS covered, just by more than one document.
        if best_score < OUT_OF_SCOPE_THRESHOLD:
            return PipelineResult(
                action="refuse_out_of_scope",
                answer=("I don't have information about that in the HR policy "
                        "documents I have access to. You may want to check with "
                        "HR directly rather than rely on me for this."),
                retrieved_score=best_score,
                retrieved_chunks=hits,
            )

        clarify_response = check_ambiguous(query, hits)
        if clarify_response:
            return PipelineResult(action="clarify", answer=clarify_response,
                                   retrieved_chunks=hits)

        answer_text = self.generator.generate(query, hits)
        return PipelineResult(
            action="answer",
            answer=answer_text,
            retrieved_doc=best_chunk.doc_id,
            retrieved_score=float(best_score),
            retrieved_chunks=hits,
        )

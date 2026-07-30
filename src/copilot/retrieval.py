import hashlib
import math
import re
from collections import Counter

from copilot.domain import Citation, KnowledgeChunk, KnowledgeDocument

TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
VECTOR_SIZE = 128


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def hash_vector(tokens: list[str]) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def chunk_document(document: KnowledgeDocument, max_words: int = 120) -> list[KnowledgeChunk]:
    words = document.body.split()
    chunks: list[KnowledgeChunk] = []
    for position, start in enumerate(range(0, len(words), max_words)):
        text = " ".join(words[start : start + max_words])
        tokens = tokenize(f"{document.title} {text}")
        chunks.append(
            KnowledgeChunk(
                id=f"{document.id}:C{position + 1}",
                document_id=document.id,
                title=document.title,
                text=text,
                position=position,
                tokens=tokens,
                vector=hash_vector(tokens),
            )
        )
    return chunks


class HybridRetriever:
    def __init__(self, documents: list[KnowledgeDocument]) -> None:
        self._chunks = [chunk for document in documents for chunk in chunk_document(document)]

    def search(self, query: str, limit: int = 3) -> list[Citation]:
        query_tokens = tokenize(query)
        query_counts = Counter(query_tokens)
        query_vector = hash_vector(query_tokens)
        scored: list[tuple[float, KnowledgeChunk]] = []
        for chunk in self._chunks:
            chunk_counts = Counter(chunk.tokens)
            overlap = sum(min(count, chunk_counts[token]) for token, count in query_counts.items())
            lexical = overlap / max(1, len(set(query_tokens)))
            semantic = max(0.0, cosine(query_vector, chunk.vector))
            score = min(1.0, 0.72 * lexical + 0.28 * semantic)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].document_id, item[1].position))
        return [
            Citation(
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                title=chunk.title,
                score=round(score, 4),
                excerpt=chunk.text[:240],
            )
            for score, chunk in scored[:limit]
        ]

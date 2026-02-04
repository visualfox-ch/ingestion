from sentence_transformers import SentenceTransformer
from .observability import embedding_cache, metrics, get_logger, log_with_context
import time

logger = get_logger("jarvis.embed")

# BGE-small: 384 dims, better quality than MiniLM, same speed
# See: https://huggingface.co/BAAI/bge-small-en-v1.5
# Compatible with existing vectors (same 384 dimensions)
MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model

def embed_texts(texts):
    """Embed texts with caching.

    - Single-text queries (common for search) hit cache directly.
    - Batch queries reuse cached entries and only encode misses.
    """
    if not texts:
        return []

    start_time = time.time()
    model = get_model()

    # Preserve order and length
    results = [None] * len(texts)

    cache_hits = 0
    cache_misses = 0
    missing_texts = []
    missing_idxs = []

    for i, t in enumerate(texts):
        # Normalize None to empty string defensively
        t = t if t is not None else ""
        key = embedding_cache._make_key(t)
        cached = embedding_cache.get(key)
        if cached is not None:
            results[i] = cached
            cache_hits += 1
        else:
            missing_texts.append(t)
            missing_idxs.append(i)
            cache_misses += 1

    if cache_hits:
        metrics.inc("embedding_cache_hits", cache_hits)
    if cache_misses:
        metrics.inc("embedding_cache_misses", cache_misses)

    # Compute only missing embeddings (if any)
    if missing_texts:
        computed = model.encode(missing_texts, normalize_embeddings=True).tolist()
        for idx, emb, t in zip(missing_idxs, computed, missing_texts):
            results[idx] = emb
            embedding_cache.set(embedding_cache._make_key(t), emb)

        metrics.inc("embeddings_computed", len(missing_texts))

    duration_ms = (time.time() - start_time) * 1000
    metrics.timing("embedding_latency_ms", duration_ms)

    log_with_context(
        logger,
        "info",
        "Embeddings served",
        count=len(texts),
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        computed=len(missing_texts),
        latency_ms=round(duration_ms, 1),
    )

    return results

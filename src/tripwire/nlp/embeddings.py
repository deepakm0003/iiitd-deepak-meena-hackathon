"""Sentence embeddings (MiniLM) for event clustering, novelty and the SetFit classifier body."""

from tripwire.config import load_yaml


class Embedder:
    def __init__(self, cfg: dict | None = None, device: str | None = None) -> None:
        cfg = cfg or load_yaml("models.yaml")["embedding"]
        self.name = cfg["name"]
        self._device = device
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            from tripwire.nlp.device import device

            self._model = SentenceTransformer(self.name, device=self._device or device())
        return self._model

    @property
    def dimension(self) -> int:
        return self._load().get_sentence_embedding_dimension()

    def encode(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        """Unit-normalised vectors, so the dot product is the cosine similarity."""
        vectors = self._load().encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                      show_progress_bar=False, convert_to_numpy=True)
        return [v.round(5).tolist() for v in vectors]


def cosine(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=True)))

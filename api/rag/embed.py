"""Dense embeddings via LSA (TF-IDF -> TruncatedSVD, 256 dims, L2-normalised).

Runs fully offline with no model download, so the project works on any laptop.
The interface (fit / embed) is the same one a hosted multilingual model such as
bge-m3 would sit behind; swapping it only changes EMBEDDING_MODEL and dims.
"""
import pickle

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import Normalizer

from ..config import ROOT

MODEL_PATH = ROOT / "data" / "embedder.pkl"
EMBEDDING_MODEL = "lsa-tfidf-svd-256@1"
DIMS = 256
_model = None


def fit(texts: list[str]):
    global _model
    tfidf = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=2, max_df=0.6, stop_words="english")
    _model = make_pipeline(tfidf, TruncatedSVD(n_components=DIMS, random_state=42), Normalizer(copy=False))
    _model.fit(texts)
    MODEL_PATH.write_bytes(pickle.dumps(_model))
    return _model


def model():
    global _model
    if _model is None:
        _model = pickle.loads(MODEL_PATH.read_bytes())
    return _model


def embed(texts: list[str]) -> np.ndarray:
    return model().transform(texts).astype(np.float32)

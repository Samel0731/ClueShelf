"""Local multilingual E5 embeddings. Runtime never downloads model files."""
from pathlib import Path
import threading
from typing import Literal

MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
DIMENSIONS = 384
MODEL_DIR = Path(__file__).resolve().parents[2] / "data/models/multilingual-e5-small"
_lock = threading.Lock()
_runtime = None


class EmbeddingUnavailable(RuntimeError):
    pass


def is_available() -> bool:
    return (MODEL_DIR / "onnx/model.onnx").is_file() and (MODEL_DIR / "tokenizer.json").is_file()


def _load():
    if not is_available():
        raise EmbeddingUnavailable("語意搜尋模型尚未安裝，請執行 scripts/setup_search.py。")
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(MODEL_DIR / "onnx/model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        return session, tokenizer
    except Exception as error:
        raise EmbeddingUnavailable("語意搜尋模型無法載入，請檢查本機模型與 ONNX 依賴。") from error


def mean_pool(hidden, attention):
    import numpy as np
    mask = attention[..., None].astype(np.float32)
    pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
    return pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)


def embed(texts: list[str], kind: Literal["query", "passage"] = "passage") -> list[list[float]]:
    if kind not in {"query", "passage"}:
        raise ValueError("kind must be query or passage")
    if not texts:
        return []
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = _load()
        session, tokenizer = _runtime
        try:
            import numpy as np
            result = []
            for start in range(0, len(texts), 8):
                encoded = tokenizer.encode_batch([f"{kind}: {text}" for text in texts[start:start + 8]])
                arrays = {"input_ids": np.array([e.ids for e in encoded], dtype=np.int64), "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64), "token_type_ids": np.array([e.type_ids for e in encoded], dtype=np.int64)}
                inputs = {item.name: arrays[item.name] for item in session.get_inputs()}
                hidden = session.run(None, inputs)[0]
                pooled = mean_pool(hidden, arrays["attention_mask"])
                if pooled.shape != (len(encoded), DIMENSIONS) or not np.isfinite(pooled).all():
                    raise ValueError("Unexpected embedding output")
                result.extend(pooled.tolist())
            return result
        except Exception as error:
            raise EmbeddingUnavailable("本地語意搜尋處理失敗，請重試或改用關鍵字搜尋。") from error

"""Local Julia-1 choice-model reranking for a bounded retrieval shortlist.

The optional model package and weights are loaded only when this reranker is used.
Candidate text is passed to a local CPU model; no text is sent to a service.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import hashlib
import math
import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from orbit.retrieval.rerank import RerankUnavailable
from orbit.retrieval.strategies import Candidate

MAX_CHOICES = 20
MAX_OPTION_TOKENS = 40  # Below Julia's per-option strict encoding limit of 48 tokens.
HEAD_LENGTH = 512
MIN_HEAD_TOKENS = 16
EXPECTED_MODEL_REVISION = "a85b127321d580d65176c89ced8273f305745d85"
EXPECTED_WEIGHTS_SHA256 = "df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72"
EXPECTED_SOURCE_SHA256 = "e3ab30c5aa6b8d05e53fc549b30b7d4f6e3aa6dede8fb6dfd701783c8526a8c0"
EXPECTED_TOKENIZER_SHA256 = "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f"
EXPECTED_TOKENIZER_CONFIG_SHA256 = "6b069e57db0ce0794c22547725275f22618809c4ef4249307337e651a0dfef8c"
EXPECTED_ENCODER_CONFIG_SHA256 = "c79cda42d42ddf777218254845ce92fb25a10dc35874be40d06abd707894523d"
EXPECTED_JULIA_CONFIG_SHA256 = "b9b881646beeac5414eaa78b39d3fe89ff8a2c062731ad718432620f9aee6bf7"


def _rss_bytes() -> int | None:
    """Return current Linux RSS without adding a runtime dependency."""
    try:
        with open("/proc/self/status", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


class Julia1Reranker:
    """Use Julia-1's finite-choice distribution to order existing candidates."""

    name = "julia-1"

    def __init__(self, model_path: str | Path | None, *, engine=None) -> None:
        self.model_path = Path(model_path).expanduser() if model_path else None
        self._engine = engine
        self._load_error: RerankUnavailable | None = None
        self._lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self.load_ms: float | None = 0.0 if engine is not None else None
        self.warmup_ms: float | None = 0.0 if engine is not None else None
        self.rss_before_bytes: int | None = None
        self.rss_after_bytes: int | None = None
        self.weights_file_bytes: int | None = None
        self.torch_threads: int | None = None
        self.torch_version: str | None = None

    @staticmethod
    def _sha256(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    @classmethod
    def _source_sha256(cls, root: Path) -> str:
        entries = []
        for path in sorted((root / "julia").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            entries.append(f"{cls._sha256(path)}  {path.relative_to(root).as_posix()}\n")
        return hashlib.sha256("".join(entries).encode("utf-8")).hexdigest()

    @staticmethod
    def _option_text(candidate: Candidate) -> str:
        parts = [candidate.record_type.replace("_", " ")]
        section = candidate.source.get("section")
        document = candidate.source.get("document")
        if section:
            parts.append(str(section))
        if document:
            parts.append(str(document))
        parts.append(candidate.content.strip())
        return ": ".join(part for part in parts if part)

    def _load(self):
        with self._lock:
            if self._load_error is not None:
                raise self._load_error
            if self._engine is not None:
                return self._engine
            try:
                if not (3, 11) <= sys.version_info[:2] < (3, 14):
                    raise RerankUnavailable("Julia-1 requires Python 3.11–3.13; baseline ranking retained")
                if self.model_path is None:
                    raise RerankUnavailable(
                        "set CELESTIN_SYSTEM1_MODEL_PATH to a local Julia-1 checkout and checkpoint; "
                        "baseline ranking retained"
                    )
                root = self.model_path.resolve(strict=True)
                required = (root / "model.safetensors", root / "julia" / "__init__.py",
                            root / "tokenizer" / "tokenizer.json", root / "tokenizer" / "tokenizer_config.json",
                            root / "encoder" / "config.json", root / "julia_config.json")
                if not all(path.is_file() for path in required):
                    raise RerankUnavailable(
                        "local Julia-1 directory is incomplete; download the pinned model repository; "
                        "baseline ranking retained"
                    )
                expected_files = {
                    root / "model.safetensors": EXPECTED_WEIGHTS_SHA256,
                    root / "tokenizer" / "tokenizer.json": EXPECTED_TOKENIZER_SHA256,
                    root / "tokenizer" / "tokenizer_config.json": EXPECTED_TOKENIZER_CONFIG_SHA256,
                    root / "encoder" / "config.json": EXPECTED_ENCODER_CONFIG_SHA256,
                    root / "julia_config.json": EXPECTED_JULIA_CONFIG_SHA256,
                }
                if any(self._sha256(path) != expected for path, expected in expected_files.items()):
                    raise RerankUnavailable(
                        "Julia-1 model artifact checksum does not match the pinned revision; baseline ranking retained"
                    )
                if self._source_sha256(root) != EXPECTED_SOURCE_SHA256:
                    raise RerankUnavailable(
                        "Julia-1 runtime source does not match the pinned revision; baseline ranking retained"
                    )

                # The model repository is a Python package, not a PyPI dependency. Import it
                # from the explicitly configured local checkout, and reject a name collision.
                existing = sys.modules.get("julia")
                if existing is not None:
                    origin = Path(getattr(existing, "__file__", "")).resolve()
                    if not origin.is_relative_to(root):
                        raise RerankUnavailable(
                            "a different 'julia' Python package is already loaded; baseline ranking retained"
                        )
                elif str(root) not in sys.path:
                    sys.path.insert(0, str(root))

                transformer_version = importlib.metadata.version("transformers")
                try:
                    major_minor = tuple(int(part) for part in transformer_version.split(".")[:2])
                except ValueError as exc:
                    raise RerankUnavailable(
                        "could not verify the installed Transformers version; baseline ranking retained"
                    ) from exc
                if not (5, 0) <= major_minor < (5, 1):
                    raise RerankUnavailable("Julia-1 requires Transformers >=5.0,<5.1; baseline ranking retained")

                module = importlib.import_module("julia")
                origin = Path(getattr(module, "__file__", "")).resolve()
                if not origin.is_relative_to(root):
                    raise RerankUnavailable(
                        "Julia-1 package did not load from the configured local directory; baseline ranking retained"
                    )

                import torch

                self.torch_version = str(torch.__version__)
                self.torch_threads = max(1, min(4, os.cpu_count() or 1))
                torch.set_num_threads(self.torch_threads)
                self.rss_before_bytes = _rss_bytes()
                self.weights_file_bytes = (root / "model.safetensors").stat().st_size
                started = time.perf_counter()
                self._engine = module.load_model(
                    str(root), device="cpu", strict_encoding=True, backend="torch",
                    max_length=8192, head_length=HEAD_LENGTH, bend_postprocess=False,
                    compile_model=False, memory_map=True,
                )
                self.load_ms = (time.perf_counter() - started) * 1000

                # Exercise the complete local path once so mmap-backed weights are resident
                # before resource measurements and the first real retrieval request.
                warmup_started = time.perf_counter()
                self._engine.predict(
                    state="local inference warmup",
                    questions={"choice": {"type": "choice", "instructions": "Choose the more relevant item.",
                                           "criteria": {"a": "relevant memory", "b": "unrelated text"}}},
                )
                self.warmup_ms = (time.perf_counter() - warmup_started) * 1000
                self.rss_after_bytes = _rss_bytes()
                return self._engine
            except RerankUnavailable as exc:
                self._engine = None
                self._load_error = exc
                raise
            except Exception as exc:
                # Keep errors content-free: requests and candidate text must not enter logs.
                self._engine = None
                self._load_error = RerankUnavailable(
                    f"Julia-1 unavailable ({type(exc).__name__}); baseline ranking retained"
                )
                raise self._load_error from exc

    def health_check(self) -> dict[str, int | float | str | None]:
        """Load and warm the configured local model; used by the explicit evaluator."""
        self._load()
        return {
            "name": self.name,
            "revision": EXPECTED_MODEL_REVISION,
            "weights_sha256": EXPECTED_WEIGHTS_SHA256,
            "source_sha256": EXPECTED_SOURCE_SHA256,
            "tokenizer_sha256": EXPECTED_TOKENIZER_SHA256,
            "python_version": ".".join(str(part) for part in sys.version_info[:3]),
            "torch_version": self.torch_version,
            "transformers_version": importlib.metadata.version("transformers"),
            "load_ms": self.load_ms,
            "warmup_ms": self.warmup_ms,
            "rss_before_bytes": self.rss_before_bytes,
            "rss_after_bytes": self.rss_after_bytes,
            "weights_file_bytes": self.weights_file_bytes,
            "torch_threads": self.torch_threads,
        }

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[str]:
        ids = [candidate.record_id for candidate in candidates]
        if not 2 <= len(candidates) <= MAX_CHOICES:
            raise RerankUnavailable("Julia-1 accepts between 2 and 20 candidates")
        if len(ids) != len(set(ids)):
            raise RerankUnavailable("candidate IDs must be unique")

        engine = self._load()
        instructions = "Which candidate is most useful for answering the query? Choose one."
        question_head = engine.tokenizer(
            f"choice question: {instructions}", add_special_tokens=False
        )["input_ids"]
        option_budget = min(
            MAX_OPTION_TOKENS,
            (HEAD_LENGTH - MIN_HEAD_TOKENS - len(question_head)) // len(candidates) - 1,
        )
        if option_budget < 4:
            raise RerankUnavailable(
                "shortlist exceeds Julia-1's strict question-head budget; baseline ranking retained"
            )
        criteria: dict[str, str] = {}
        option_to_record: dict[str, str] = {}
        for index, candidate in enumerate(candidates):
            option_id = f"candidate_{index:02d}"
            text = self._option_text(candidate)
            mask = getattr(engine.tokenizer, "mask_token", None)
            if mask:
                text = text.replace(mask, " ")
            # Julia encodes options with a leading space. Budget that same sequence so
            # strict_encoding accepts large shortlists without dropping question context.
            token_ids = engine.tokenizer(" " + text, add_special_tokens=False)["input_ids"]
            if len(token_ids) > option_budget:
                text = engine.tokenizer.decode(token_ids[:option_budget], skip_special_tokens=True).strip()
            criteria[option_id] = text or candidate.record_type.replace("_", " ")
            option_to_record[option_id] = candidate.record_id

        try:
            with self._inference_lock:
                response = engine.predict(
                    state=query,
                    questions={"relevance": {
                        "type": "choice",
                        "instructions": instructions,
                        "criteria": criteria,
                    }},
                )
            probabilities = response["answers"]["relevance"]["probabilities"]
            if not isinstance(probabilities, dict) or set(probabilities) != set(option_to_record):
                raise ValueError("choice probabilities do not match supplied options")
            values = []
            for option_id, probability in probabilities.items():
                if isinstance(probability, bool) or not isinstance(probability, (int, float)):
                    raise ValueError("choice probability is not numeric")
                probability = float(probability)
                if not math.isfinite(probability) or not 0 <= probability <= 1:
                    raise ValueError("choice probability is outside [0, 1]")
                values.append((option_to_record[option_id], probability))
            if not math.isclose(sum(value for _, value in values), 1.0, rel_tol=1e-4, abs_tol=1e-4):
                raise ValueError("choice probabilities are not normalized")
            original_position = {record_id: index for index, record_id in enumerate(ids)}
            return [record_id for record_id, _ in sorted(
                values, key=lambda row: (-row[1], original_position[row[0]])
            )]
        except RerankUnavailable:
            raise
        except Exception as exc:
            raise RerankUnavailable(
                f"Julia-1 inference failed ({type(exc).__name__}); baseline ranking retained"
            ) from exc


@lru_cache(maxsize=4)
def build_julia1_reranker(model_path: str | None) -> Julia1Reranker:
    """Reuse one lazy model object per path for the life of the server process."""
    return Julia1Reranker(model_path)

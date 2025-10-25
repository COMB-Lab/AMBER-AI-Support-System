from abc import ABC, abstractmethod
import os
from transformers import AutoTokenizer, pipeline

# ---- Config ----
DEFAULT_MODEL = os.getenv("AMBER_LLM_MODEL", "google/flan-t5-large")
MAX_INPUT_TOKENS = 512  # FLAN-T5 input context

# ---- Lazy singletons ----
_TOKENIZER = None
_GENERATOR = None

def _get_tokenizer(model_name: str):
    global _TOKENIZER
    if _TOKENIZER is None:
        _TOKENIZER = AutoTokenizer.from_pretrained(model_name, use_fast=True)
    return _TOKENIZER

def _get_generator(model_name: str):
    global _GENERATOR
    if _GENERATOR is None:
        _GENERATOR = pipeline(
            "text2text-generation",
            model=model_name,
            truncation=True,
        )
    return _GENERATOR


class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str, *, temperature: float, max_tokens: int) -> str: ...


class HuggingFaceLLM(BaseLLM):
    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self.tokenizer = _get_tokenizer(model_name)
        self.generator = _get_generator(model_name)

    def _clip_to_context(self, text: str) -> str:
        ids = self.tokenizer.encode(text, add_special_tokens=True, truncation=True, max_length=MAX_INPUT_TOKENS)
        return self.tokenizer.decode(ids, skip_special_tokens=True)

    def generate(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 200) -> str:
        prompt = self._clip_to_context(prompt)
        use_sampling = temperature and temperature > 0.0
        outputs = self.generator(
            prompt,
            max_new_tokens=max_tokens,
            min_new_tokens=32,        # <-- ensure it writes something
            do_sample=use_sampling,
            temperature=max(0.0, min(2.0, float(temperature))) if use_sampling else None,
            top_p=0.95 if use_sampling else None,
            num_beams=1,
            no_repeat_ngram_size=3,   # <-- avoid degenerate repeats
            truncation=True,
        )
        return outputs[0]["generated_text"]


def call_llm(system: str, user: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
    prompt = f"{system}\n\n{user}"
    llm = HuggingFaceLLM()
    return llm.generate(prompt, temperature=temperature, max_tokens=max_tokens)
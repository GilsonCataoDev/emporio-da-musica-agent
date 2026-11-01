"""Model-chain behaviour of GeminiLLM, with a fake client (no network, no API key)."""

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from emporio import llm
from emporio.llm import GeminiLLM


def make_llm(behaviour: dict, models=("a", "b", "c")):
    """GeminiLLM whose client runs `behaviour[model]`: an exception to raise or a value to return."""
    calls: list[str] = []

    def generate_content(model, contents, config):
        calls.append(model)
        outcome = behaviour[model]
        if isinstance(outcome, list):  # one outcome per attempt on this model
            outcome = outcome.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    instance = object.__new__(GeminiLLM)
    instance.models = list(models)
    instance.model = instance.models[0]
    instance._config = None
    instance._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return instance, calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)


def api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_timeout_moves_to_the_next_model_without_retrying_the_slow_one():
    instance, calls = make_llm({"a": httpx.ReadTimeout("slow"), "b": "ok", "c": "unused"})
    assert instance._generate([]) == "ok"
    assert calls == ["a", "b"]                      # one try on "a", then straight to "b"
    assert instance.models[0] == "b" and instance.model == "b"


def test_connection_error_is_retried_on_the_same_model():
    instance, calls = make_llm({"a": [httpx.ConnectError("down"), "ok"], "b": "unused", "c": "unused"})
    assert instance._generate([]) == "ok"
    assert calls == ["a", "a"]


def test_every_model_timing_out_raises_the_timeout():
    instance, calls = make_llm({m: httpx.ReadTimeout("slow") for m in "abc"})
    with pytest.raises(httpx.ReadTimeout):
        instance._generate([])
    assert calls == ["a", "b", "c"]


def test_overload_is_retried_then_falls_through_to_the_next_model():
    instance, calls = make_llm({"a": [api_error(503), api_error(503)], "b": "ok", "c": "unused"})
    assert instance._generate([]) == "ok"
    assert calls == ["a", "a", "b"]


@pytest.mark.parametrize("code", [404, 429])
def test_missing_model_or_exhausted_quota_skips_to_the_next_model(code):
    instance, calls = make_llm({"a": api_error(code), "b": "ok", "c": "unused"})
    assert instance._generate([]) == "ok"
    assert calls == ["a", "b"]


def test_bad_request_is_raised_immediately():
    instance, calls = make_llm({"a": api_error(400), "b": "unused", "c": "unused"})
    with pytest.raises(errors.APIError):
        instance._generate([])
    assert calls == ["a"]

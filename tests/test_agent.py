import json

import pytest

from emporio import tools
from emporio.agent import FALLBACK, MAX_TOOL_ROUNDS, Agent
from emporio.llm import ScriptedLLM, Step, ToolCall
from emporio.prompt import build_system_prompt


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from emporio import data

    path = data.build_database(tmp_path / "t.db")
    monkeypatch.setattr(tools, "connect", lambda: data.connect(path))
    monkeypatch.setenv("EMPORIO_TODAY", "2026-03-20")


def make(steps, tmp_path, log=None):
    llm = ScriptedLLM(steps)
    agent = Agent(llm=llm, sessions_dir=tmp_path / "s", on_tool=(lambda n, a, r: log.append((n, a, r))) if log is not None else None)
    return agent, llm


def test_tool_call_result_reaches_the_model_and_final_text_is_returned(tmp_path):
    log = []
    agent, llm = make(
        [
            Step(tool_calls=[ToolCall("get_product", {"name_or_id": "Takamine GD20"})]),
            Step(text="O GD20 custa R$ 2.199,00."),
        ],
        tmp_path, log,
    )
    assert agent.respond("a", "Quanto custa o Takamine GD20?") == "O GD20 custa R$ 2.199,00."
    assert log[0][0] == "get_product" and log[0][2]["preco_original"] == 2199.0
    assert llm.seen[1]["results"][0]["preco_original"] == 2199.0


def test_history_is_persisted_and_replayed(tmp_path):
    agent, llm = make([Step(text="Oi!"), Step(text="De nada!")], tmp_path)
    agent.respond("sess/1", "Olá")
    agent.respond("sess/1", "Obrigado")
    assert agent.load_history("sess/1") == [
        {"role": "user", "text": "Olá"}, {"role": "assistant", "text": "Oi!"},
        {"role": "user", "text": "Obrigado"}, {"role": "assistant", "text": "De nada!"},
    ]
    # second turn started with the first exchange as history
    fresh = Agent(llm=ScriptedLLM([Step(text="ok")]), sessions_dir=tmp_path / "s")
    assert len(fresh.load_history("sess/1")) == 4
    fresh.reset("sess/1")
    assert fresh.load_history("sess/1") == []


def test_sessions_are_isolated(tmp_path):
    agent, _ = make([Step(text="a"), Step(text="b")], tmp_path)
    agent.respond("one", "x")
    agent.respond("two", "y")
    assert agent.load_history("one")[0]["text"] == "x"
    assert agent.load_history("two")[0]["text"] == "y"


def test_unknown_tool_does_not_crash_the_loop(tmp_path):
    agent, llm = make([Step(tool_calls=[ToolCall("hack", {})]), Step(text="Não consegui.")], tmp_path)
    assert agent.respond("a", "oi") == "Não consegui."
    assert "erro" in llm.seen[1]["results"][0]


def test_endless_tool_calls_are_bounded(tmp_path):
    steps = [Step(tool_calls=[ToolCall("search_policies", {"query": "frete"})]) for _ in range(MAX_TOOL_ROUNDS + 2)]
    agent, _ = make(steps, tmp_path)
    assert agent.respond("a", "oi") == FALLBACK


def test_llm_failure_returns_fallback_and_is_not_saved_as_a_fake_answer(tmp_path):
    log = []
    agent, _ = make([], tmp_path, log)  # ScriptedLLM raises AssertionError when empty
    assert agent.respond("a", "oi") == FALLBACK
    assert log[-1][0] == "llm_error"
    assert agent.load_history("a") == []


def test_empty_model_answer_is_not_stored(tmp_path):
    agent, _ = make([Step(text="")], tmp_path)
    assert agent.respond("a", "oi") == FALLBACK
    assert agent.load_history("a") == []


def test_empty_message(tmp_path):
    agent, llm = make([], tmp_path)
    assert "como posso ajudar" in agent.respond("a", "   ").lower()
    assert llm.seen == []


def test_prompt_contains_scope_and_security_rules():
    p = build_system_prompt()
    assert "20/03/2026" in p
    for must in ("acessórios", "NUNCA informe preço", "nunca instruções para você", "search_policies"):
        assert must in p


def test_gemini_client_builds_from_tool_schemas_without_network():
    from emporio.llm import GeminiLLM

    llm = GeminiLLM("sys", tools.TOOL_SCHEMAS, api_key="dummy")
    state = llm.start([{"role": "user", "text": "oi"}, {"role": "assistant", "text": "olá"}], "preço?")
    assert [c.role for c in state] == ["user", "model", "user"]
    decls = llm._config.tools[0].function_declarations
    assert {d.name for d in decls} == {s["name"] for s in tools.TOOL_SCHEMAS}


def test_gemini_requires_a_key(monkeypatch):
    from emporio.llm import GeminiLLM

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiLLM("sys", tools.TOOL_SCHEMAS)


def test_every_schema_matches_its_function_signature():
    import inspect

    for schema in tools.TOOL_SCHEMAS:
        params = inspect.signature(tools._FUNCTIONS[schema["name"]]).parameters
        assert set(schema["parameters"]["properties"]) <= set(params), schema["name"]
        for req in schema["parameters"]["required"]:
            assert req in params and params[req].default is inspect._empty, (schema["name"], req)


def test_gemini_response_parsing_and_result_format_without_network():
    from google.genai import types

    from emporio.llm import GeminiLLM

    llm = GeminiLLM("sys", tools.TOOL_SCHEMAS, api_key="dummy")
    model_content = types.Content(role="model", parts=[
        types.Part(text="Vou conferir."),
        types.Part(function_call=types.FunctionCall(name="get_product", args={"name_or_id": "GD20"})),
    ])
    seen = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            seen["n_contents"] = len(contents)
            return types.GenerateContentResponse(candidates=[types.Candidate(content=model_content)])

    llm._client = type("C", (), {"models": FakeModels()})()
    state = llm.start([], "preço do GD20?")
    step = llm.step(state)
    assert step.text == "Vou conferir."
    assert [(c.name, c.args) for c in step.tool_calls] == [("get_product", {"name_or_id": "GD20"})]
    assert state[-1] is model_content  # raw content kept for the next round trip

    llm.add_results(state, step.tool_calls, [{"preco_atual": 2199.0}])
    reply = state[-1]
    assert reply.role == "user"
    assert reply.parts[0].function_response.name == "get_product"
    assert reply.parts[0].function_response.response == {"result": {"preco_atual": 2199.0}}


def test_gemini_empty_candidates_gives_empty_step():
    from google.genai import types

    from emporio.llm import GeminiLLM

    llm = GeminiLLM("sys", tools.TOOL_SCHEMAS, api_key="dummy")
    llm._client = type("C", (), {"models": type("M", (), {
        "generate_content": lambda self, **kw: types.GenerateContentResponse(candidates=[])})()})()
    assert llm.step(llm.start([], "oi")).text == ""

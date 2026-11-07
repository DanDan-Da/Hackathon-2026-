import json

from app.ingest import rule_compiler as rc
from app.ingest.rule_compiler import ExtractedBatch, ExtractedRule
from app.ingest.rules_loader import Chunk
from app.models import CheckType, Rule
from app.providers.llm import LLMProvider, LLMRefusal

TEXT = ("V404.2.3 Clear Width. Door openings shall provide a clear\nwidth of 32 inches minimum.\n"
        "V403.5.1 The clear width of walking surfaces shall be 36 inches minimum.")


def er(**kw):
    base = dict(title="Door width", check_type=CheckType.numeric, target="Door", parameter="clear_width",
                operator=">=", value_number=32, unit="in", clause="V404.2.3",
                quote="Door openings shall provide a clear width of 32 inches minimum.")
    base.update(kw)
    return ExtractedRule(**base)


class FakeLLM(LLMProvider):
    def __init__(self, rules=None, fail=False):
        self.rules, self.fail, self.calls = rules or [], fail, []

    def complete(self, system, prompt):
        raise NotImplementedError

    def complete_structured(self, system, prompt, schema, images_png=None):
        self.calls.append(prompt)
        if self.fail:
            raise LLMRefusal("nope")
        return ExtractedBatch(rules=self.rules)


def chunk(text=TEXT, doc="pvag.pdf", page=3):
    return Chunk("REG", doc, page, text)


def test_valid_rule_gets_provenance_from_chunk_not_model():
    [r] = rc.extract_chunk(chunk(), FakeLLM([er()]))
    assert (r.source.regime, r.source.document, r.source.page) == ("REG", "pvag.pdf", 3)
    assert r.target == "door" and r.value == 32 and r.unit == "in"
    # quote matched despite the line break in the source text
    assert r.source.quote == "Door openings shall provide a clear width of 32 inches minimum."


def test_hallucinated_quote_dropped(caplog):
    bad = er(quote="Doors shall be 40 inches wide.")
    assert rc.extract_chunk(chunk(), FakeLLM([bad, er()])).__len__() == 1
    assert "DROPPED (quote not in source)" in caplog.text


def test_structurally_invalid_dropped():
    assert rc.extract_chunk(chunk(), FakeLLM([er(value_number=None)])) == []
    assert rc.extract_chunk(chunk(), FakeLLM([er(check_type=CheckType.presence, operator=">=")])) == []
    q = er(check_type=CheckType.qualitative, parameter=None, operator=None, value_number=None, unit=None)
    assert len(rc.extract_chunk(chunk(), FakeLLM([q]))) == 1


def test_dedup_on_regime_clause_parameter_and_unique_ids():
    llm = FakeLLM([er(), er(title="Door width again"),
                   er(clause="V403.5.1", target="corridor",
                      quote="The clear width of walking surfaces shall be 36 inches minimum.", value_number=36)])
    rules = rc.compile_rules([chunk(), chunk(page=4)], llm, max_parallel=1)
    assert len(rules) == 2
    assert len({r.id for r in rules}) == 2
    assert rules[0].title == "Door width"          # first occurrence wins


def test_failed_and_tiny_chunks_do_not_stop_run():
    assert rc.compile_rules([chunk()], FakeLLM(fail=True), max_parallel=1) == []
    llm = FakeLLM([er()])
    rc.compile_rules([chunk(text="too short")], llm, max_parallel=1)
    assert llm.calls == []                          # tiny chunk never sent to the model


def test_reviewed_rules_survive_recompile():
    [new] = rc.compile_rules([chunk()], FakeLLM([er()]), max_parallel=1)
    edited = new.model_copy(update={"value": 30.0, "reviewed": True})
    merged = rc.keep_reviewed([new], [edited])
    assert merged[0].value == 30.0 and merged[0].reviewed


def test_main_writes_rules_json(tmp_path, monkeypatch):
    (tmp_path / "rules" / "REG").mkdir(parents=True)
    (tmp_path / "rules" / "REG" / "a.txt").write_text(TEXT, encoding="utf-8")
    out = tmp_path / "out" / "rules.json"
    monkeypatch.setattr(rc.settings, "rules_dir", tmp_path / "rules")
    monkeypatch.setattr(rc.settings, "compiled_rules", out)
    monkeypatch.setattr(rc, "get_llm", lambda: FakeLLM([er()]))
    rc.main()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [Rule.model_validate(d).source.regime for d in data] == ["REG"]


def test_cache_skips_llm_on_rerun(tmp_path):
    cache = tmp_path / "rules.cache.json"
    first = FakeLLM([er()])
    a = rc.compile_rules([chunk()], first, max_parallel=1, cache_path=cache)
    assert len(first.calls) == 1 and cache.exists()
    second = FakeLLM([er(title="different")])
    b = rc.compile_rules([chunk()], second, max_parallel=1, cache_path=cache)
    assert second.calls == [] and [r.model_dump() for r in b] == [r.model_dump() for r in a]


def test_failed_chunk_not_cached_and_retried(tmp_path):
    cache = tmp_path / "rules.cache.json"
    assert rc.compile_rules([chunk()], FakeLLM(fail=True), max_parallel=1, cache_path=cache) == []
    retry = FakeLLM([er()])
    assert len(rc.compile_rules([chunk()], retry, max_parallel=1, cache_path=cache)) == 1
    assert len(retry.calls) == 1


def test_cache_saved_per_chunk_survives_partial_run(tmp_path):
    cache = tmp_path / "rules.cache.json"

    class DiesOnSecond(FakeLLM):
        def complete_structured(self, *a, **k):
            if self.calls:
                raise KeyboardInterrupt   # simulates the run being stopped mid-way
            return super().complete_structured(*a, **k)

    try:
        rc.compile_rules([chunk(page=1), chunk(page=2)], DiesOnSecond([er()]), max_parallel=1, cache_path=cache)
    except KeyboardInterrupt:
        pass
    resume = FakeLLM([er()])
    rc.compile_rules([chunk(page=1), chunk(page=2)], resume, max_parallel=1, cache_path=cache)
    assert len(resume.calls) == 1          # page 1 came from the cache, only page 2 is re-asked

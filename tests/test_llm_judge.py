"""L5: LLM judge with a fake provider (no network, no API key)."""
from app.check.evaluator import evaluate_rule
from app.check.llm_judge import JudgeVerdict, judge
from app.models import (CheckType, DesignElement, DesignFacts, Provenance, Rule, ShipParticulars,
                        SourceRef, Status)
from app.providers.llm import LLMProvider, LLMRefusal

QUOTE = "Stairways shall be readily accessible from all passenger spaces."


class FakeLLM(LLMProvider):
    def __init__(self, verdict=None, error=None):
        self.verdict, self.error, self.calls = verdict, error, 0

    def complete(self, system, prompt):
        raise NotImplementedError

    def complete_structured(self, system, prompt, schema, images_png=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.verdict


def rule():
    return Rule(id="R1", title="Stairway accessibility", check_type=CheckType.qualitative, target="stairway",
                source=SourceRef(document="d.pdf", regime="REG", page=2, clause="1.2", quote=QUOTE))


def el(id="s1", conf=1.0):
    return DesignElement(id=id, type="stairway", name="Main stair",
                         provenance=Provenance(file="ga.pdf", page=1, confidence=conf))


def verdict(**kw):
    base = dict(status="pass", reasoning="Main stair connects all decks.", evidence_ids=["s1"], clause_quote=QUOTE)
    return JudgeVerdict(**{**base, **kw})


def run(v=None, elements=None, error=None):
    llm = FakeLLM(v, error)
    return judge(rule(), elements if elements is not None else [el()], llm=llm), llm


def test_valid_pass_is_kept_with_evidence_and_quote():
    res, _ = run(verdict())
    assert res.status == Status.passed and res.evidence_ids == ["s1"] and res.clause_quote == QUOTE


def test_valid_fail_is_kept():
    assert run(verdict(status="fail"))[0].status == Status.failed


def test_quote_whitespace_differences_tolerated():
    res, _ = run(verdict(clause_quote="Stairways shall be  readily\naccessible"))
    assert res.status == Status.passed


def test_no_evidence_forces_needs_review():
    assert run(verdict(evidence_ids=[]))[0].status == Status.needs_review


def test_unknown_evidence_id_rejects_verdict():
    res, _ = run(verdict(evidence_ids=["s1", "ghost"]))
    assert res.status == Status.needs_review and "ghost" in res.reasoning


def test_non_verbatim_or_missing_quote_rejected():
    assert run(verdict(clause_quote="Stairs must be easy to reach."))[0].status == Status.needs_review
    assert run(verdict(clause_quote=None))[0].status == Status.needs_review


def test_low_confidence_evidence_forces_needs_review():
    assert run(verdict(), elements=[el(conf=0.3)])[0].status == Status.needs_review


def test_model_needs_review_passes_through():
    assert run(verdict(status="needs_review", evidence_ids=[]))[0].status == Status.needs_review


def test_llm_error_is_needs_review_not_pass():
    res, _ = run(error=LLMRefusal("declined"))
    assert res.status == Status.needs_review and "LLMRefusal" in res.reasoning


def test_no_elements_skips_llm_call():
    res, llm = run(verdict(), elements=[])
    assert res.status == Status.needs_review and llm.calls == 0


def test_evaluate_rule_routes_qualitative_to_judge_and_builds_finding():
    facts = DesignFacts(project="p", particulars=ShipParticulars(), elements=[el(), el("other")])
    llm = FakeLLM(verdict())
    f = evaluate_rule(rule(), facts, llm)[0]
    assert llm.calls == 1
    assert (f.method, f.status, f.element_id) == ("llm_judge", Status.passed, "s1")
    assert f.rule_source.quote == QUOTE and f.evidence[0].file == "ga.pdf" and f.reasoning


def test_evaluate_rule_without_matching_elements_needs_review():
    facts = DesignFacts(project="p", elements=[])
    f = evaluate_rule(rule(), facts, FakeLLM(verdict()))[0]
    assert f.status == Status.needs_review and f.method == "llm_judge"

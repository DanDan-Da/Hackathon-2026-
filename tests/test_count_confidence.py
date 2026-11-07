"""Count and presence rules must not decide on elements the extractor was unsure about."""
import pytest

from app.check.evaluator import evaluate_rule
from app.models import DesignElement, DesignFacts, Provenance, Rule, SourceRef, Status


def _rule(operator, value=None, check_type="count"):
    return Rule(id="r", title="t", check_type=check_type, target="stairway", operator=operator, value=value,
                unit="count" if value is not None else None,
                source=SourceRef(document="d.pdf", regime="X", clause="1", quote="q"))


def _facts(*confidences):
    els = [DesignElement(id=f"S{i}", type="stairway",
                         provenance=Provenance(file="ga.pdf", page=1, method="vision", confidence=c))
           for i, c in enumerate(confidences)]
    return DesignFacts(project="p", elements=els)


def _status(rule, facts):
    out = evaluate_rule(rule, facts)
    assert len(out) == 1
    return out[0].status


def test_enough_confident_elements_still_pass():
    assert _status(_rule(">=", 2), _facts(0.9, 0.9)) == Status.passed


def test_pass_that_depends_on_a_low_confidence_element_is_needs_review():
    assert _status(_rule(">=", 2), _facts(0.9, 0.3)) == Status.needs_review


def test_presence_resting_only_on_a_low_confidence_element_is_needs_review():
    assert _status(_rule("exists", check_type="presence"), _facts(0.3)) == Status.needs_review


def test_presence_with_a_confident_element_passes_even_if_another_is_doubtful():
    assert _status(_rule("exists", check_type="presence"), _facts(0.9, 0.3)) == Status.passed


def test_fail_that_a_low_confidence_element_could_rescue_is_needs_review():
    assert _status(_rule(">=", 3), _facts(0.9, 0.9, 0.2)) == Status.needs_review


def test_fail_stays_a_fail_when_no_doubtful_element_could_change_it():
    assert _status(_rule(">=", 4), _facts(0.9, 0.9, 0.2)) == Status.failed


def test_not_exists_with_only_a_doubtful_element_is_needs_review():
    assert _status(_rule("not_exists", check_type="presence"), _facts(0.3)) == Status.needs_review


def test_upper_bound_failing_with_confident_elements_is_a_definite_fail():
    assert _status(_rule("<=", 1), _facts(0.9, 0.9)) == Status.failed

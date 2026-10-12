"""Judge contract/privacidade only; no claim of semantic evaluation quality."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from scripts.evaluate_grounding import GroundingJudgement, evaluate_answer


class Judge:
    def __init__(self, output=None):
        self.calls = []
        self.output = output or {"supported": True, "score": .8, "rationale": "synthetic judgement"}

    def invoke(self, messages):
        self.calls.append(messages)
        return self.output


@pytest.mark.parametrize("output", [
    {"supported": True, "score": .5, "rationale": "x", "unsupported_claims": ["x"]},
    {"supported": False, "score": 1, "rationale": "x"},
    {"supported": True, "score": 2, "rationale": "x"},
])
def test_judge_rejects_inconsistent_or_out_of_range_contract(output):
    with pytest.raises(ValidationError):
        GroundingJudgement.model_validate(output)


@pytest.mark.parametrize("message,plan", [
    ("Qual a cotação para meu CPF 12345678909?", []),
    ("Como funciona Pix?", ["knowledge", "customer_support"]),
])
def test_private_answer_never_sent_to_judge(message, plan):
    judge = Judge()
    output = evaluate_answer({"id": "synthetic", "message": message},
                             {"answer": "SYNTHETIC_PRIVATE_MARKER", "plan": plan}, [], judge)
    assert output["status"] == "skipped_private_context" and not judge.calls


def test_abstention_and_missing_evidence_do_not_call_judge():
    judge = Judge()
    item = {"id": "synthetic", "message": "Como funciona Pix?"}
    assert evaluate_answer(item, {"requires_human": True}, [], judge)["status"] == "abstained"
    assert evaluate_answer(item, {}, [], judge)["status"] == "no_evidence"
    assert not judge.calls


def test_synthetic_judgement_and_malformed_provider_are_distinguished():
    rows = [(SimpleNamespace(metadata={"source_url": "https://site.getnet.com.br/pix/"}, page_content="synthetic pix"), .9)]
    item = {"id": "synthetic", "message": "Como funciona Pix?"}
    answer = {"answer": "synthetic answer", "plan": ["knowledge"]}
    assert evaluate_answer(item, answer, rows, Judge())["status"] == "judged"
    assert evaluate_answer(item, answer, rows, Judge({"score": "broken"}))["status"] == "judge_error"

import sys
import types
import pytest

pytest.importorskip("langchain_core")

from app.agents.knowledge import KnowledgeAgent


class BrokenRetriever:
    def retrieve(self, message):
        raise RuntimeError("store unavailable")


class EmptyRetriever:
    def retrieve(self, message):
        return []


def _agent(retriever):
    agent = object.__new__(KnowledgeAgent)
    agent.retriever = retriever
    agent.llm = None
    return agent


def test_retrieval_failure_requests_human():
    result = _agent(BrokenRetriever()).process("Getnet")
    assert result["requires_human"] is True
    assert result["confidence"] == 0.0
    assert result["errors"] == ["knowledge_retrieval: RuntimeError"]


def test_no_evidence_requests_human():
    result = _agent(EmptyRetriever()).process("Getnet")
    assert result["requires_human"] is True
    assert result["sources"] == []

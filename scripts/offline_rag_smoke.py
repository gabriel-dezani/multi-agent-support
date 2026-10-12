"""Exercise REAL KnowledgeAgent guard logic with deterministic fake retrieval/LLM.

No external provider/vector embedding is involved. This verifies provenance,
insufficient-evidence abstention, citation validation and token accounting.
"""
import sys
import types
from types import SimpleNamespace


def install_external_stubs():
    if 'langchain_core.messages' not in sys.modules:
        try:
            import langchain_core.messages
        except ImportError:
            messages=types.ModuleType('langchain_core.messages')
            messages.SystemMessage=lambda content: SimpleNamespace(content=content)
            messages.HumanMessage=lambda content: SimpleNamespace(content=content)
            core=types.ModuleType('langchain_core'); core.__path__=[]
            docs=types.ModuleType('langchain_core.documents')
            docs.Document=object
            sys.modules.update({'langchain_core':core,'langchain_core.messages':messages,
                                'langchain_core.documents':docs})
    try:
        import langchain_openai
    except ImportError:
        pkg=types.ModuleType('langchain_openai')
        pkg.ChatOpenAI=type('ChatOpenAI',(),{})
        sys.modules['langchain_openai']=pkg
    try:
        import langchain_text_splitters
    except ImportError:
        pkg=types.ModuleType('langchain_text_splitters')
        pkg.RecursiveCharacterTextSplitter=type('RecursiveCharacterTextSplitter',(),{})
        sys.modules['langchain_text_splitters']=pkg
    # Retriever initialization is mocked; actual KnowledgeAgent logic stays intact.
    try:
        import app.rag.retriever
    except ImportError:
        module=types.ModuleType('app.rag.retriever')
        module.KnowledgeRetriever=type('KnowledgeRetriever',(),{})
        sys.modules['app.rag.retriever']=module


class FakeLLM:
    def __init__(self, supported, citation_ids):
        self.supported=supported
        self.citation_ids=citation_ids
    def with_structured_output(self, schema, include_raw=False):
        assert include_raw
        self.schema=schema
        return self
    def invoke(self, messages):
        assert 'TRECHO 1' in messages[-1].content
        parsed=self.schema(answer='Pix information in official source',
                           supported=self.supported,citation_ids=self.citation_ids)
        return {'parsed':parsed,'raw':SimpleNamespace(usage_metadata={'input_tokens':21,'output_tokens':9})}


class FakeRetriever:
    def __init__(self,url='https://www.getnet.net/en',score=0.9):
        self.url=url
        self.score=score
    def retrieve(self,query):
        return [(SimpleNamespace(page_content='Pix accepts payment from customers',
                                 metadata={'source_url':self.url}),self.score)]


def main():
    install_external_stubs()
    from app.agents.knowledge import KnowledgeAgent
    total=0
    def check(value,reason):
        nonlocal total
        assert value,reason
        total+=1
    agent=KnowledgeAgent(retriever=FakeRetriever(),llm=FakeLLM(True,[1]))
    good=agent.process('What is Pix?')
    check(not good['requires_human'],'strong grounded retrieval answers')
    check(good['sources']==['https://www.getnet.net/en'],'only cited official source included')
    check(good['usage']=={'input_tokens':21,'output_tokens':9},'provider tokens propagated')
    check(good['retrieval']['hits']==1,'retrieval evidence recorded')

    missing_citations=KnowledgeAgent(retriever=FakeRetriever(),llm=FakeLLM(True,[])).process('Pix')
    check(missing_citations['requires_human'],'uncited output abstains')
    invented=KnowledgeAgent(retriever=FakeRetriever(),llm=FakeLLM(True,[99])).process('Pix')
    check(invented['requires_human'],'invented citations abstain')
    unsupported=KnowledgeAgent(retriever=FakeRetriever(),llm=FakeLLM(False,[1])).process('Pix')
    check(unsupported['requires_human'],'model self-declared unsupported abstains')
    spoofed=KnowledgeAgent(retriever=FakeRetriever(url='https://evil.org/fake'),llm=FakeLLM(True,[1])).process('Pix')
    check(spoofed['requires_human'],'non-Getnet source not accepted')
    irrelevant=KnowledgeAgent(retriever=FakeRetriever(score=0.1),llm=FakeLLM(True,[1])).process('Pix')
    check(irrelevant['requires_human'],'insufficient retrieval relevance abstains')
    print(f'PASS: {total} grounded-RAG assertions (fake evidence and LLM; real KnowledgeAgent).')


if __name__=='__main__':
    main()

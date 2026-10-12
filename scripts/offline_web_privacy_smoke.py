"""Exercise WebSearchAgent's actual process() privacy boundary with fake providers.

External searches and OpenAI calls are intentionally replaced by recording fakes.
This is not a Tavily integration test.
"""
import asyncio
import sys
import types


def install_missing_message_types():
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        return
    except ImportError:
        package = types.ModuleType('langchain_core')
        package.__path__ = []
        messages = types.ModuleType('langchain_core.messages')
        class Message:
            def __init__(self, content):
                self.content = content
        messages.HumanMessage = Message
        messages.SystemMessage = Message
        package.messages = messages
        sys.modules['langchain_core'] = package
        sys.modules['langchain_core.messages'] = messages
    try:
        import langchain_openai
    except ImportError:
        provider = types.ModuleType('langchain_openai')
        provider.ChatOpenAI = object
        sys.modules['langchain_openai'] = provider


async def main():
    install_missing_message_types()
    from app.agents.web_search_agent import WebSearchAgent
    class Tool:
        def __init__(self): self.calls=[]
        async def execute(self, query):
            self.calls.append(query)
            return [{'url':'https://example.com/fx','title':'FX','content':'FX market information'}]
    class LLM:
        def __init__(self): self.prompts=[]
        async def ainvoke(self, messages):
            self.prompts.extend(m.content for m in messages)
            return types.SimpleNamespace(content='Respondeu usando fontes.')
    tool=Tool(); llm=LLM()
    agent=WebSearchAgent(tool=tool,llm=llm)
    count=0
    def check(value, reason):
        nonlocal count
        assert value,reason
        count+=1

    result=await agent.process('Cotação do dólar para CPF 12345678909 e email alice@example.com',
                               history=[{'role':'user','content':'MINHAS VENDAS PRIVADAS'}])
    check(not result['requires_human'], 'public price query continues safely')
    check(tool.calls==['current USD BRL exchange rate'], 'external tool sees canonical public query')
    check(all('CPF' not in x and '12345678909' not in x and 'alice@example.com' not in x
              and 'MINHAS VENDAS PRIVADAS' not in x for x in llm.prompts), 'generation receives no original identifier or private history')

    prior=len(tool.calls)
    result=await agent.process('Pesquise o extrato da conta CPF 12345678909')
    check(result['requires_human'], 'unsafe search is denied')
    check(len(tool.calls)==prior, 'blocked query never reaches provider')

    # RAG recovery may not send a partially private Getnet message.
    result=await agent.process('Como funciona Getnet Pix CPF 12345678909?', official_only=True)
    check(result['requires_human'], 'unsafe official recovery denied')
    check(len(tool.calls)==prior, 'official-only block is independent')
    print(f'PASS: {count} actual WebSearchAgent privacy assertions (faked external providers).')

if __name__=='__main__':
    asyncio.run(main())

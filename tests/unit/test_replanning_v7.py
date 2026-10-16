from app.orchestration.review_policy import bounded_replan, choose_next


def example(message='Explique Pix Getnet', agent='knowledge', plan=None):
    return {'message':message, 'plan':plan or [agent], 'current_step':1,
            'agent_results':[{'agent':agent,'requires_human':True,'confidence':0.0,
                              'sources':[]}]}


def test_knowledge_failover_to_official_web_only_when_safe_and_enabled():
    state = example()
    replan = bounded_replan(state, web_available=True)
    assert replan == {'plan':['knowledge', 'web_search'], 'web_getnet_only':True}
    assert choose_next(state | replan) == 'web_search'
    assert bounded_replan(state, web_available=False) == {}
    assert bounded_replan(state | {'plan':['knowledge','web_search','customer_support']},
                          web_available=True) == {}


def test_official_web_can_switch_back_to_rag_without_new_tools():
    state=example(agent='web_search')
    replan = bounded_replan(state, web_available=False)
    assert replan == {'plan':['web_search','knowledge'], 'rag_getnet_recovery':True}
    assert choose_next(state | replan) == 'knowledge'


def test_no_private_data_in_replanning_and_no_cyclic_retries():
    assert bounded_replan(example('minhas vendas Pix',plan=['knowledge']),web_available=True) == {}
    assert bounded_replan(example(plan=['knowledge','customer_support']),web_available=True) == {}
    assert bounded_replan(example(agent='web_search',plan=['knowledge','web_search']),web_available=True) == {}
    safe = example()
    safe['agent_results'][0].update({'requires_human':False,'confidence':.9,
                                     'sources':['https://site.getnet.com.br/pix/']})
    assert bounded_replan(safe,web_available=True) == {}


def test_successful_rag_fallback_resolves_failed_web_subtask():
    from app.orchestration.review_policy import unresolved
    state=example(agent='web_search')
    state.update(bounded_replan(state,web_available=True))
    state['current_step']=2
    state['agent_results'].append({'agent':'knowledge','requires_human':False,
                                    'answer':'Resposta sustentada pela fonte Pix.',
                                    'sources':['https://site.getnet.com.br/pix/'],
                                    'confidence':.9})
    assert unresolved(state) == []
    assert choose_next(state) == 'synthesis'

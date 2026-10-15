from app.rag.verification import verify_claims, second_pass_verify


def test_fake_numeric_fee_requires_exact_evidence():
    sources=['https://site.getnet.com.br/pix/']
    evidence=['Pix com taxa de 1,5% por venda e prazo de 2 dias.']
    assert verify_claims('Taxa de 1,5% e prazo 2 dias', evidence, sources)[0]
    assert not verify_claims('Taxa de 7% e prazo 2 dias', evidence, sources)[0]


def test_unsubstantiated_guarantee_now_abstains():
    good, why = verify_claims('Getnet garante lucro infinito.',
                              ['pix evidence without monetary guarantee'],
                              ['https://site.getnet.com.br/pix/'])
    assert good is False
    assert 'unsupported_absolute_claim:infinite' in why


def test_forged_citation_is_rejected():
    assert not verify_claims('Saiba mais em https://evil.example/fee',
            ['Pix existe'], ['https://site.getnet.com.br/pix/'])[0]


def test_unsupported_inference_is_not_automatically_claimed_verified():
    # Known limitation: heuristic cannot prove semantic entailment. Fail-closed
    # optional structured second-pass LLM is required for harder assertions.
    class BrokenJudge:
        def with_structured_output(self, *_):
            raise RuntimeError('provider down')
    assert second_pass_verify(llm=BrokenJudge(), question='Pix?', answer='yes',evidence=['Pix']) is False


def test_citation_marker_is_not_mistaken_for_fabricated_amount():
    ok, problems = verify_claims('Informação pública sintética baseada no trecho 1.',
                                  ['pix: conteúdo público sintético'],
                                  ['https://site.getnet.com.br/pix/'])
    assert ok and not problems

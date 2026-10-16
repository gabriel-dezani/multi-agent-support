"""Resolve elliptical follow-ups without inheriting unrelated older intents.

Consecutive subjectless turns share one nearest explicit topic anchor. A fresh
explicit subject starts a new task even if it begins with 'E' / 'And'.
"""
import re
import unicodedata


def _normalize(text: str) -> str:
    text = unicodedata.normalize('NFD', text or '')
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return ' '.join(text.casefold().split())


def is_contextual_followup(message: str) -> bool:
    text = _normalize(message).strip(' ?!.')
    if not text:
        return False
    # Subjectless amount questions refer back; a named subject must not match.
    if re.fullmatch(
        r'(?:e )?(?:quant[oa]s? (?:foi|foram|deu|deram|ficou|ficaram|custou|custaram)|'
        r'qual (?:foi|era|e) o (?:valor|total))(?: (?:isso|isto|aquilo))?', text
    ):
        return True
    # Explicitly named new topics are NOT contextual, despite the initial 'E'.
    if re.match(r'^(e quanto ao?|e sobre|what about|how about|and what about)\s+', text):
        tail = re.sub(r'^(e quanto ao?|e sobre|what about|how about|and what about)\s+', '', text)
        return bool(re.fullmatch(
            r'(isso|isto|aquilo|it|that|this|o mesmo|a mesma|ontem|yesterday|hoje|today|amanha|tomorrow)[ ?!.]*',
            tail,
        ))
    return bool(re.search(
        r'^(e isso\b|e isto\b|e ontem\b|e hoje\b|e amanha\b|e agora\b|'
        r'and yesterday\b|and today\b|and now\b|and what about (it|that)\b|'
        r'and what should i do now\b|and can i .{0,60}\bit\b|'
        r'isso\b|isto\b|that\b|it\b|o mesmo\b|a mesma\b|the same\b)', text
    )) or text in {'e', 'and', 'e?', 'and?'}


def contextual_user_anchor(message: str, history: list[dict] | None) -> str:
    """Resolve consecutive ellipses to ONE anchor, never merge old topics."""
    if (history and history[-1].get('topic_recalled') and
            re.match(r'^(retome|retomar|volte|voltar|return|resume)\s', _normalize(message))):
        return str(history[-1].get('context_anchor') or '')[:500]
    if not is_contextual_followup(message):
        return ''
    for row in reversed(history or []):
        if row.get('role') == 'user':
            if row.get('resolved_topic'):
                return str(row['resolved_topic'])[:500]
            content = str(row.get('content') or '')
            if not is_contextual_followup(content):
                return content[:500]
            # An elliptical-looking turn can still introduce an explicit topic
            # ("E isso no Pix?"). Stop there instead of reviving older support.
            from app.agents.router import RouterAgent
            normalized = RouterAgent.normalize(content)
            explicit = (RouterAgent._matches(normalized, RouterAgent.SUPPORT) or
                        RouterAgent._matches(normalized, RouterAgent.KNOWLEDGE) or
                        RouterAgent._matches(normalized, RouterAgent.HUMAN) or
                        [term for term in RouterAgent._matches(normalized, RouterAgent.CURRENT)
                         if term not in {"hoje", "today", "agora", "now"}])
            if explicit:
                return content[:500]
    return str((history or [{}])[-1].get('context_anchor') or '')[:500]

"""Durable deterministic topic anchors shared by SQLite and PostgreSQL.

Only explicit user topics are indexed. No generated summary or model call.
The additive migration backfills legacy rows once, in bounded read batches.
The anchor lives on the message, so clear/TTL cannot leave private summaries.
"""
import re

from app.orchestration.context import contextual_user_anchor, _normalize


def topic_anchor(content):
    return contextual_user_anchor('E isso?', [{'role':'user', 'content':content}]) or None


def migrate_topics(db, *, postgres=False):
    if postgres:
        columns = {row[0] for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
            "AND table_name='conversation_messages'").fetchall()}
    else:
        columns = {row[1] for row in db.execute('PRAGMA table_info(conversation_messages)').fetchall()}
    if 'topic_anchor' not in columns:
        db.execute('ALTER TABLE conversation_messages ADD COLUMN topic_anchor TEXT')
        after = 0
        while True:
            rows = db.execute("SELECT id,content FROM conversation_messages WHERE role='user' "
                              "AND id>? ORDER BY id LIMIT 500", (after,)).fetchall()
            if not rows:
                break
            for identifier, content in rows:
                anchor = topic_anchor(content)
                if anchor:
                    db.execute('UPDATE conversation_messages SET topic_anchor=? WHERE id=?', (anchor,identifier))
            after = rows[-1][0]
    db.execute('CREATE INDEX IF NOT EXISTS idx_memory_topics '
               'ON conversation_messages(conversation_id,user_id,id) WHERE topic_anchor IS NOT NULL')


def recall_terms(message):
    text = _normalize(message or '')
    match = re.match(r'^(?:retome|retomar|volte|voltar|return|resume)\s+(?:(?:ao?|o|the)\s+)?'
                     r'(?:(?:assunto|topico|topic)\s+)?(.+)', text)
    if not match:
        return []
    ignored = {'de','do','da','dos','das','sobre','a','o','the','to','about'}
    return [word for word in re.findall(r'\w{2,}',match[1]) if word not in ignored][:8]


def previous_topic(db, conversation_id, user_id, before, message):
    """Indexed nearest anchor, or a scoped explicit topic recall.

    Named recall scans anchors only, in pages; the message window stays fixed.
    Requiring every search term avoids selecting a vaguely related old topic.
    """
    terms = recall_terms(message)
    cursor = before
    while True:
        rows = db.execute('SELECT id,topic_anchor FROM conversation_messages '
                          'WHERE conversation_id=? AND user_id=? AND id<? '
                          'AND topic_anchor IS NOT NULL ORDER BY id DESC LIMIT ?',
                          (conversation_id,user_id,cursor,100 if terms else 1)).fetchall()
        for identifier, anchor in rows:
            if not terms or all(term in _normalize(anchor).split() for term in terms):
                return anchor
        if not terms or not rows:
            return ''
        cursor = rows[-1][0]


def write_topic(db, conversation_id, user_id, content):
    if recall_terms(content):
        return previous_topic(db,conversation_id,user_id,2**63-1,content) or None
    return topic_anchor(content)


def expose_resolved_topics(history):
    """Carry a resumed topic across the next elliptical turn, without rewriting text."""
    for row in history:
        anchor = row.pop('topic_anchor', None)
        if row.get('role') == 'user' and recall_terms(row.get('content')) and anchor:
            row['resolved_topic'] = anchor

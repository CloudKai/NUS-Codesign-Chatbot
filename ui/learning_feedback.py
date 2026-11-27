"""Small explicit learning-feedback controls and best-effort display receipts."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from backend.learning_signals import learning_receipts
from ui.runtime import store, rerun_fragment

logger = logging.getLogger(__name__)


def record_display(message_id: str) -> None:
    """Record one explicit recommendation opening per session after rendering it.

    A failed telemetry write must never prevent reading or confirming saved work.
    Failed writes are retried on a later render; successful receipts are durable.
    """
    key = f'learning-displayed:{st.session_state.thread_id}:{message_id}'
    if st.session_state.get(key):
        return
    try:
        store.record_learning_signal(st.session_state.thread_id, message_id, 'recommendation_displayed')
    except Exception:
        logger.warning('Recommendation display receipt unavailable')
    else:
        st.session_state[key] = True


def render_answer_feedback(message: dict[str, Any]) -> None:
    """Offer optional usefulness feedback on freeform answers and report save failures."""
    metadata = message.get('metadata') or {}
    if metadata.get('interaction_intent') not in {'lecture_help', 'improve_design'} or message.get('is_error'):
        return
    rating = (learning_receipts(metadata.get('learning_signals')).get('rating') or {}).get('kind')
    st.write('Was this answer useful?')
    with st.container(horizontal=True):
        for kind, label in [('useful', 'Useful'), ('not_useful', 'Not useful')]:
            if st.button(label, key=f'learning-{kind}-{message["id"]}',
                         type='primary' if rating == kind else 'secondary'):
                try:
                    receipts = store.record_learning_signal(st.session_state.thread_id, message['id'], kind)
                except Exception:
                    st.error('Your feedback could not be saved. Try again.')
                else:
                    # The bounded transcript window survives fragment reruns.
                    # Refresh only the acknowledged rating, preserving loaded pages.
                    metadata['learning_signals'] = receipts.model_dump(mode='json', exclude_none=True)
                    rerun_fragment()
    if rating:
        st.write('Feedback saved. You can change it.')

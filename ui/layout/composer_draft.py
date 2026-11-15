"""Preserve unsent composer text within the current browser tab and notebook."""
from __future__ import annotations

import hashlib
import json

import streamlit.components.v1 as components

from ui.html_embed import wrap_component_html


def composer_scope(owner: str, thread_id: str) -> str:
    """Return an opaque identity for this owner's notebook (or unsaved chat)."""
    return hashlib.sha256(f'{owner}\0{thread_id or "draft"}'.encode()).hexdigest()


def sync_composer_draft(owner: str, thread_id: str, *, submitted: bool) -> None:
    """Restore text after remount/reload; clear only on an explicit text send.

    Drafts use sessionStorage scoped to an opaque owner/notebook key. They stay
    in this browser tab, never enter the transcript, and exclude file contents.
    Browser storage denial leaves the native composer usable.
    """
    key = composer_scope(owner, thread_id)
    context = json.dumps({'key': f'codesign:draft:v1:{key}', 'scope': key, 'submitted': submitted})
    script = r"""
<script>
(() => {
  const win = window.parent;
  const doc = win.document;
  const context = __CONTEXT__;
  const selector = `.st-key-chat_composer [class*="st-key-composer-${context.scope}-"] [data-testid="stChatInputTextArea"]`;
  if (win.__cdDraftCleanup) win.__cdDraftCleanup();
  const read = () => { try { return win.sessionStorage.getItem(context.key) || ''; } catch (_) { return ''; } };
  const save = (value) => { try {
    if (value) win.sessionStorage.setItem(context.key, value);
    else win.sessionStorage.removeItem(context.key);
  } catch (_) {} };
  if (context.submitted) save('');
  let restoring = false;
  const restore = () => {
    const input = doc.querySelector(selector);
    if (!input || input.disabled || input.dataset.cdDraftKey === context.key) return;
    const changedScope = input.dataset.cdDraftKey && input.dataset.cdDraftKey !== context.key;
    input.dataset.cdDraftKey = context.key;
    const value = read();
    if (!changedScope && (!value || input.value)) return;
    restoring = true;
    const setter = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new win.Event('input', { bubbles: true }));
    restoring = false;
  };
  const onInput = (event) => {
    if (!restoring && event.target.matches && event.target.matches(selector)) save(event.target.value);
  };
  const onSend = (event) => {
    const target = event.target;
    const input = doc.querySelector(selector);
    if (!input || input.disabled) return;
    const enter = event.type === 'keydown' && target === input && event.key === 'Enter' && !event.shiftKey && !event.isComposing;
    const button = event.type === 'click' && target.closest && target.closest('.st-key-chat_composer [data-testid="stChatInputSubmitButton"]:not(:disabled)');
    if ((enter || button) && input.value.trim()) save('');
  };
  doc.addEventListener('input', onInput, true);
  doc.addEventListener('keydown', onSend, true);
  doc.addEventListener('click', onSend, true);
  const observer = new win.MutationObserver(restore);
  observer.observe(doc.body, { childList: true, subtree: true });
  win.__cdDraftCleanup = () => {
    observer.disconnect();
    doc.removeEventListener('input', onInput, true);
    doc.removeEventListener('keydown', onSend, true);
    doc.removeEventListener('click', onSend, true);
  };
  restore();
})();
</script>
"""
    components.html(wrap_component_html(script.replace('__CONTEXT__', context)), height=0)

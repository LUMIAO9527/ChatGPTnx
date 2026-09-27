"""Outcome capabilities shared by the durable queue and generated UI.

Only results known to precede text insertion or Invoke may be explicitly retried.
A timeout after a side effect is never included, regardless of its user label.
"""
ATTENTION_REASONS = frozenset({
    'user_draft_present', 'composer_in_use', 'composer_state_unknown',
    'composer_unavailable', 'user_attachment_present', 'automatic_send_unavailable',
})
RETRYABLE_REASONS = ATTENTION_REASONS | frozenset({
    'target_not_visible', 'desktop_not_running', 'desktop_window_ambiguous',
    'input_guard_unavailable', 'input_focus_changed',
    'composer_selection_unavailable', 'selection_not_collapsed',
    'desktop_bridge_unavailable', 'desktop_task_not_idle',
    'resume_source_unconfigured',
    'title_unavailable_or_ambiguous',
    'task_identity_unavailable', 'task_navigation_unconfirmed', 'desktop_location_unreadable',
})

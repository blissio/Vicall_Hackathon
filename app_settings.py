"""Non-secret workspace preferences and explicit experimental AI selection."""
import os
from storage import load_document, save_document


def read(workspace):
    value = load_document(workspace.directory/'app_settings.json', {})
    return {'ai_mode': value.get('ai_mode', 'cloud'), 'simple_navigation': value.get('simple_navigation', True)}


def status(workspace):
    from local_ai import installed, LOCK
    value = read(workspace)
    local_allowed = getattr(workspace, 'local_ai_test_enabled', False)
    cloud = bool(os.getenv('OPENAI_API_KEY') and os.getenv('VICALL_AI_MODEL'))
    ready = installed() if local_allowed else False
    available = ready if value['ai_mode'] == 'local_test' else cloud if value['ai_mode'] == 'cloud' else False
    return {**value, 'local_test_enabled': local_allowed, 'local_installed': ready, 'local_busy': LOCK.locked(), 'cloud_configured': cloud, 'ai_available': available,
            'model': 'Qwen2.5 0.5B · local test' if value['ai_mode'] == 'local_test' else os.getenv('VICALL_AI_MODEL', '') if value['ai_mode'] == 'cloud' else '',
            'google_lab_configured': bool(os.getenv('PAGESPEED_API_KEY')), 'google_field_configured': bool(os.getenv('CRUX_API_KEY') or os.getenv('PAGESPEED_API_KEY'))}


def save(workspace, payload):
    mode = payload.get('ai_mode')
    simple = payload.get('simple_navigation')
    if mode not in {'off', 'cloud', 'local_test'} or type(simple) is not bool:
        raise ValueError('Choose a valid AI mode and navigation preference')
    if mode == 'local_test' and not getattr(workspace, 'local_ai_test_enabled', False):
        raise ValueError('Local AI is a temporary experiment. Launch with --local-ai-test to enable it.')
    with workspace.lock:
        save_document(workspace.directory/'app_settings.json', {'ai_mode': mode, 'simple_navigation': simple})
    return status(workspace)

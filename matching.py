"""User-defined matching criteria with an explicit, inspectable rubric."""
import re
from storage import load_document, save_document

DEFAULT_WEIGHTS = {'relevance': 35, 'observed_need': 20, 'public_contact': 10, 'reviewed_role': 10,
                   'recent_evidence': 10, 'reviewed_identity': 5, 'partner_fit': 10}
STOP = set('a an and or the of for to with in services service business businesses local'.split())


def terms(text):
    return {word for word in re.findall(r'[a-z0-9]+', text.casefold()) if len(word) > 1} - STOP


def service_match(requested, supplied):
    wanted = terms(requested)
    if not wanted:
        return 0.0, []
    matches = sorted(wanted & terms(supplied))
    return len(matches)/len(wanted), matches


def load_weights(directory):
    saved = load_document(directory / 'matching_settings.json', {})
    return {**DEFAULT_WEIGHTS, **saved.get('weights', {})}


def save_weights(directory, payload):
    weights = payload.get('weights')
    if not isinstance(weights, dict) or set(weights) != set(DEFAULT_WEIGHTS):
        raise ValueError('Supply each documented ranking weight')
    if any(type(value) is not int or not 0 <= value <= 100 for value in weights.values()) or not sum(weights.values()):
        raise ValueError('Weights must be integers from 0–100, with a nonzero total')
    value = {'weights': weights}
    save_document(directory / 'matching_settings.json', value)
    return value


def rank(signals, weights, intent):
    applicable = {key: value for key,value in weights.items() if not (key == 'observed_need' and intent != 'prospects') and not (key == 'partner_fit' and intent != 'partners')}
    denominator = sum(applicable.values())
    points = {key: round(min(1, max(0, signals.get(key, 0))) * weight, 2) for key,weight in applicable.items()}
    return (round(100*sum(points.values())/denominator) if denominator else 0), points

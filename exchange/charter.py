"""Versioned community charter; readable without the neural or cryptographic runtime."""
import copy
import hashlib
import json

_CHARTER_V1 = {
    'version': 1,
    'motto': 'Coopérer librement, préserver le vivant, respecter chaque personne.',
    'purpose': 'Un réseau communautaire mondial d\'entraide et d\'échanges utiles, construit par des communautés autonomes.',
    'principles': [
        'La participation est volontaire. Chaque propriétaire décide des autorisations de ses appareils et de ses échanges.',
        'Les personnes sont respectées sans discrimination. Les conditions de participation sont publiques et discutées collectivement.',
        'Les données personnelles sont minimisées. Leur vente et le profilage imposé ne font pas partie du projet.',
        'La réparation, le réemploi, le partage et les services utiles sont privilégiés. Les impacts environnementaux sont mesurés avant toute affirmation.',
        'Les règles communes sont explicites. Les engagements acceptés et les différends sont traités selon des procédures convenues par les participants.',
        'LOCAL sert aux échanges communautaires. Le projet exclut la conversion fiduciaire, les intérêts, la spéculation et les promesses de rendement.',
        'La technique assiste les personnes. Un modèle sémantique ne peut accorder un droit, signer pour un propriétaire ou imposer une décision.'
    ],
    'protocol_commitments': {
        'unit': 'LOCAL',
        'fiat_conversion_allowed': False,
        'interest': 0,
        'protocol_fee': 0,
        'owner_consent_required': True,
        'bilateral_exchange_consent_required': True,
        'credit_debt_conservation_required': True
    }
}


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def community_charter():
    return copy.deepcopy(_CHARTER_V1)


def charter_hash(document):
    return hashlib.sha256(_encode(document)).hexdigest()


def validate_charter(document):
    if not isinstance(document, dict) or _encode(document) != _encode(_CHARTER_V1):
        raise ValueError('Unsupported or altered community charter; a new version needs explicit consent')


def print_charter(document):
    validate_charter(document)
    print(f'Charte communautaire - version {document["version"]}')
    print(document['motto'])
    print(document['purpose'])
    for number, principle in enumerate(document['principles'], 1):
        print(f'{number}. {principle}')
    print(f'Empreinte de la charte : {charter_hash(document)}')

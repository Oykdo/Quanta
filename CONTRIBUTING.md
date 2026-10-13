# Contribuer

Les contributions aux sources du réseau sont proposées sous AGPL-3.0-only.
Conserver les notices d'origine et identifier clairement les changements.

## Avant une proposition

1. Décrire le problème et les invariants concernés.
2. Ajouter une vérification indépendante : conservation des soldes, autorisation,
   nonces, allocation unique, redémarrage ou bornes de stockage.
3. Exécuter `python -B scripts/check.py` depuis la racine.
4. Utiliser uniquement des identités synthétiques dans les exemples publiés.

Une évolution du schéma, de la charte, de l'allocation ou des limites doit
comporter une migration explicitement autorisée et une vérification de compatibilité.
Un changement de code ne vaut pas consentement rétroactif des participants.

Les correctifs de sécurité doivent garder une reproduction minimale et ne pas
inclure de clés ou données d'un utilisateur. Le contact privé du dépôt doit
être choisi avant l'ouverture d'un service public.

## Revue

Les modifications ordinaires demandent une revue et des tests réussis. Les
changements de règles de distribution ou de gouvernance demandent une proposition
publique, un délai de discussion et l'accord prévu par la communauté pilote.
Ne pas fusionner un changement de règle seulement parce qu'il augmente un débit
mesuré ou le nombre de comptes : les droits et les invariants priment.

# Sécurité et périmètre actuel

Le pilote utilise des wallets synthétiques, un coordinateur local et une API
sur 127.0.0.1. Il n'est pas un réseau monétaire public ou un consensus mondial.
Les tests couvrent signatures, nonces, répétitions, limites, allocation et stockage.

Un signalement doit indiquer : version du code, invariant violé, reproduction
minimale avec des clés artificielles et impact observé. Un incident impliquant
une clé ou des données personnelles demande un canal privé du dépôt ; ce canal
doit être configuré par les mainteneurs avant publication et utilisation réelles.

Les fichiers de clés, coffres, bases, journaux d'exécution et tokens ne doivent
pas être joints à une issue. Un correctif doit avoir une vérification et préserver
la possibilité d'auditer les engagements déjà acceptés.

Une exposition à d'autres machines nécessite transport authentifié et chiffré,
enrôlement, gestion de clés, politique de panne et revue du protocole. Le nom
d'un dépôt public ou une empreinte RFC 3161 ne certifie pas ces garanties.

# Charte morale du réseau communautaire

## Devise

> **Coopérer librement, préserver le vivant, respecter chaque personne.**

La finalité est un réseau parallèle d'entraide et d'échanges utiles pour la
communauté mondiale. Il s'appuie sur des communautés autonomes qui choisissent
leurs modalités de participation et peuvent coopérer entre elles.

Cette devise est une orientation morale. **LOCAL** est seulement l'unité de
compte des échanges du prototype ; aucune conversion en monnaie fiduciaire,
parité avec l'euro, réserve bancaire ou promesse de rendement ne fait partie du
projet. Le bénéfice recherché est l'accès à des biens, services et capacités
réelles, dans le respect des engagements et des ressources disponibles.

## Les sept principes

1. **Consentement et autonomie.** La participation est volontaire. Le propriétaire
   autorise les usages de ses appareils et ses échanges ; il peut refuser et
   suspendre son compte selon des modalités explicites.
2. **Dignité et inclusion.** Les personnes sont respectées sans discrimination.
   Les conditions d'admission sont publiques, discutées collectivement et adaptées
   aux capacités de chaque communauté.
3. **Vie privée.** Les données personnelles sont minimisées. Le projet n'organise
   ni leur vente ni un profilage imposé. Les participants choisissent les règles
   de visibilité et de conservation nécessaires aux engagements communs.
4. **Préservation du vivant.** Réparation, réemploi, partage, services utiles et
   sobriété sont privilégiés. Une affirmation écologique doit s'appuyer sur des
   mesures ; une faible taille de fichier ne suffit pas à prouver un faible impact.
5. **Responsabilité collective.** Les règles sont compréhensibles et les engagements
   acceptés sont traçables. Les différends et les difficultés de contribution sont
   traités selon des procédures convenues, avec écoute des personnes concernées.
6. **Échanges communautaires.** LOCAL sert aux échanges, avec équilibre entre
   crédits et débits. Conversion fiduciaire, intérêts, spéculation et promesses de
   rendement sont exclus de la finalité du projet.
7. **Technique au service des personnes.** Un modèle sémantique peut aider à
   formuler une demande. Il ne peut accorder un droit, signer pour un propriétaire
   ou imposer une décision.

## Acceptation explicite et versionnée

Les nouveaux registres utilisent le protocole **V2** et contiennent la charte
morale **version 1**. Le contenu exact est affiché lors de l'adhésion. Sa signature
porte sur l'identité du groupe, ses limites et l'empreinte de la charte.

La référence technique signée est le document structuré retourné par le CLI :

```powershell
.\.venv\Scripts\python.exe -B -m exchange.lab charter
.\.venv\Scripts\python.exe -B -m exchange.lab charter --json
```

Ces commandes de lecture n'ont besoin ni de PyTorch ni de la bibliothèque
cryptographique. Pour inspecter la charte effectivement inscrite dans un registre :

```powershell
python -B -m exchange.lab charter --ledger CHEMIN/ledger.json
```

Un refus d'adhésion laisse le registre inchangé. Une charte modifiée ou une
empreinte différente est rejetée. Un changement de principes demande une
nouvelle version prise en charge et de nouvelles autorisations explicites ;
les signatures existantes ne valent pas acceptation de nouveaux engagements.

Les registres historiques V1 restent auditables avec leurs signatures originales.
Ils sont signalés comme **sans acceptation signée de cette charte**. Aucun
consentement rétroactif n'est inventé.

## Du prototype local à la communauté mondiale

Le développement vise une **fédération de communautés autonomes**, plutôt
qu'une collecte centralisée de tous les échanges du monde. Les terminaux
conservent les reçus utiles ; les règles de partage entre groupes doivent être
limitées et acceptées par les personnes concernées.

Les prochains jalons sont : fiabilité après panne, interface propriétaire
compréhensible, petit réseau authentifié, puis accords d'interopérabilité entre
communautés. Les échanges intergroupes demanderont un règlement vérifiable,
des limites communes et une prévention de la double utilisation des crédits.
La communication mondiale et ce règlement intergroupes sont des objectifs de
développement, pas des fonctions déjà déployées.

Le code vérifie les signatures, les limites, la conservation des soldes et le
format des opérations. Il n'accepte aucun champ de conversion fiduciaire dans
une transaction. Une signature d'adhésion atteste un accord au document ; elle
ne prouve pas à elle seule le respect de tous les principes dans la vie réelle.
Le soin du vivant, l'équité et la résolution des différends demandent aussi des
pratiques collectives et des mesures accessibles aux participants.

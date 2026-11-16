# Migration vers un agent de développement inspiré de LingCore

Date : 15 novembre 2026. Base examinée : révision `8da0858` du projet et archive locale LingCore `0.6.1`.

## 1. Objectif et décision d’architecture

Remplacer le pipeline fixe par **une session d’agent de développement, persistante pendant une génération**, capable de lire les exigences, explorer le projet, modifier plusieurs couches, exécuter des commandes et vérifier le résultat dans le navigateur.

Le projet possède actuellement 13 passes numérotées de `00` à `12`. Ce document décrit leur abandon comme mécanisme d’exécution. Les étapes de migration ci-dessous sont des tâches pour développer le nouveau système ; elles ne deviennent pas des phases obligatoires pour chaque application générée.

### Architecture retenue pour ce plan

Développer **notre propre moteur dans ce dépôt**, en s’inspirant des mécanismes de LingCore : boucle conversationnelle, appels d’outils, observations, mémoire, streaming, sessions et budgets. Réutiliser les composants utiles du projet actuel et implémenter progressivement les capacités manquantes.

LingCore est une référence de conception et de comparaison. Le moteur livré ne doit ni importer `lingcore`, ni installer son package, ni embarquer son runtime. L’archive locale reste une source d’étude. Les adaptateurs éventuellement nécessaires relient notre moteur aux fournisseurs de modèles ; ils ne délèguent pas son exécution à LingCore.

La première livraison construit un noyau réduit et testable. La mémoire avancée, le navigateur, la persistance sur disque et les politiques complètes de réparation arrivent dans les étapes suivantes. Il n’est pas nécessaire de reproduire toutes les fonctionnalités de LingCore.

Le nouveau chemin nominal est :

```text
CLI existante + profil de génération
                 |
                 v
Préparation locale : exigences, ressources, workspace, dépendances
                 |
                 v
Une session de notre moteur pour l’application
  lire / chercher / planifier / éditer / exécuter / observer
                 ^                              |
                 |                              v
                 +------- observations et erreurs
                 |
        proposition de fin de l’agent
                 |
                 v
Vérification finale indépendante de l’hôte
    succès -> livrer
    échec réparable -> observations dans la même session
    budget épuisé / incident terminal -> résultat explicite
```

L’agent choisit un ordre de travail adapté à l’application. Il peut construire un parcours complet, revenir sur un schéma, changer une API ou corriger une page sans attendre une passe particulière.

Les contraintes imposées par l’hôte concernent les entrées, le périmètre d’accès, les budgets, la protection des tests et l’acceptation finale. Il n’impose plus de produire successivement cinq représentations globales avant de pouvoir écrire du code.

## 2. Ce qui motive le changement, et ce qui reste à mesurer

### Constats dans le code actuel

- `infrastructure/compiler.py` appelle les 13 passes dans un ordre fixe.
- `TextModel.generate_json()` reconstruit une requête structurée ; la boucle d’édition renvoie notamment la tâche et l’état des fichiers sélectionnés.
- La conception produit successivement schéma, obligations, API, UI et triggers. Ces documents ont un coût de génération, de transmission et de maintenance.
- Plusieurs implémentations et vérifications sont organisées par couche, puis raccordées dans le frontend.
- La passe `07` affiche le contrat des API sans effectuer une revue sémantique supplémentaire. La passe `04` réalise notamment une vérification des symboles et un affichage.
- Les installations et contrôles sont déclenchés par les étapes ; le nouveau système doit pouvoir les réutiliser sans reproduire cette orchestration.
- Les outils du modèle sont actuellement `read_file` et `edit_file`. Les recherches sémantiques passent par `context_request`, un protocole propre au compilateur.

### Indices dans les traces historiques

| Trace locale | Observation | Conséquence pour la migration |
| --- | --- | --- |
| `outputs/cost-baseline-5of5.json` | 75 appels comptabilisés, 1 341 518 tokens d’entrée cumulés ; étape `12` : 1 773 secondes sur 2 966. | Mesurer en priorité le contexte renvoyé et le coût de l’intégration frontend. |
| `outputs/cost-unfinished-target-loop.json` | 277 appels comptabilisés à l’étape `08`, encore inachevée dans la trace. | Ajouter un suivi du progrès et une stratégie de sortie des répétitions. |

Ces traces concernent d’anciennes exécutions. Elles ne décrivent pas automatiquement le comportement de la révision actuelle et ne constituent pas une comparaison contrôlée avec LingCore. Leurs noms de fichiers ne servent pas de preuve du score Arcbench.

Le nombre de passes ne suffit pas à expliquer la consommation. Un agent libre peut aussi multiplier les recherches, les résumés et les essais. Une limite de sortie élevée n’est pas une consommation effective. La migration doit mesurer le nombre total de requêtes, le volume de contexte, le travail répété et le résultat livré.

## 3. Périmètre à conserver, transformer et retirer

| Élément actuel | Traitement cible |
| --- | --- |
| CLI `main.py INPUT --output-dir OUTPUT --port PORT` | Conserver la compatibilité principale ; remplacer son moteur. |
| `requirements.yaml`, références et scénarios | Conserver comme sources de vérité, avec accès ciblé et conservation des contraintes parentes. |
| `normalize_requirements()` et indexation des exigences | Réutiliser les parties déterministes ; compléter la validation des formes et identifiants. |
| Templates React / Express / SQLite | Conserver pour la première migration afin d’isoler l’effet du moteur ; retirer leurs attentes envers les anciennes passes. |
| Utilitaires de fichiers, processus et ports | Réutiliser après découplage des étapes. |
| Tests HTTP et Playwright | Réutiliser les mécanismes d’exécution ; détacher les attentes des anciennes IR. |
| Acceptation indépendante | Conserver et adapter pour fonctionner sans `backend_apis.json`, `ui_design.json` ni `frontend_triggers.json` obligatoires. |
| Git et archives d’échecs | Conserver sous forme de points de reprise utiles, sans checkpoint verbeux systématique après chaque observation. |
| Schéma / obligations / API / UI / triggers globaux | Retirer du chemin obligatoire ; permettre une note de conception locale si la tâche en a besoin. |
| Boucles `propose_json()` et `run_file_agent()` | Remplacer dans le chemin nominal par notre boucle conversationnelle. |
| Registre et protocole JSON des outils actuels | Réutiliser les exécuteurs utiles derrière un registre local typé et des appels d’outils natifs. |
| Scripts `00` à `12` | Retirer de l’exécution puis supprimer lorsque leurs dépendances utiles ont été déplacées. |
| `IDEES_AMELIORATION_AGENT.md` | Conserver comme historique d’hypothèses ; signaler que le présent plan remplace sa stratégie fondée sur le pipeline. |

## État de la partie A

Les étapes 1 à 4 disposent maintenant de leur implémentation : référence figée sous
`benchmarks/baseline/`, protocole et cas de comparaison, types et client modèle locaux,
boucle de conversation, outils de fichiers, profil et chargeur propres au projet.
L’installation et les tests hors ligne ne nécessitent pas LingCore.

Les rapports historiques disponibles sont archivés ; les sorties complètes et réglages
exacts de ces anciens runs ne sont pas établis. Les comparaisons réelles et la sonde
fournisseur restent à exécuter explicitement. Aucun score Arcbench nouveau n’est revendiqué.
`main.py` reste le point d’entrée évalué par les tests propres à Arcbench pendant la
migration ; la bascule du moteur complet a eu lieu à l’étape 20 (voir l’état de la partie D). Les cases ouvertes dans A correspondent aux validations externes.

Validation locale : les 26 tests ciblés (noyau, profil, transport simulé, référence et
packaging) passent. L’archive de soumission a été extraite et installée avec le lockfile
dans un environnement neuf ; la CLI historique, le chargement du profil et les tests
du noyau et du packaging y fonctionnent. La suite historique complète n’est pas verte :
elle a été interrompue après plusieurs échecs et un blocage. Deux échecs (affichage
console et exemple de conception UI) sont reproduits sur la référence figée ; les
autres ne sont pas tous diagnostiqués. Ces contrôles locaux ne constituent pas une
évaluation par les tests externes Arcbench.

## État de la partie B

Les étapes 5 à 12 sont implémentées dans `infrastructure/runtime/` et vérifiées le
15 novembre 2026. La revue a corrigé quatre défauts qui empêchaient un usage réel :

- **Étape 10** — la fermeture du navigateur se bloquait indéfiniment : depuis Python 3.12,
  `Server.wait_closed()` attend aussi les connexions actives, et le proxy loopback
  l’appelait avant d’annuler ses relais. Toute session ayant ouvert une page ne se
  fermait plus (`tests/test_agent_browser.py` ne terminait pas).
- **Étape 06** — `backend/scripts/copy-db.mjs` exigeait `src/db/seeds/`, que seule
  l’ancienne passe 05 créait (le miroir d’exécution ne réplique pas les dossiers vides) :
  `npm run build` échouait sur tout projet sans données de démarrage.
- **Étapes 08 / 13 amont** — les consignes placent les contrôles de l’agent sous
  `backend/checks`, mais le runner ne découvrait que `backend/tests` (protégé). Il
  découvre maintenant les deux, et une suite absente rend `missing` (code 3,
  `NO_API_TESTS`) au lieu de `failed` ; `tsconfig.test.json` couvre `checks/`.
  Le dernier message « step 08 » des templates est retiré.
- **Étape 10** — `process_start` rendait la main avant que le service réponde ;
  `ready_timeout` attend une réponse HTTP réelle sur chaque port déclaré (le
  publisher Docker accepte le TCP avant l’écoute du conteneur).

Validation : un essai de bout en bout scripté (modèle simulé, sandbox Docker réelle
`node:22-bookworm`, Chromium réel) sur `benchmarks/cases/development/accounts` enchaîne
catalogue d’exigences, `verify_application` → `missing`, installation npm, éditions
SQL/API/UI/check dans un même lot, refus d’écriture dans `backend/tests`, build, tests
`backend/checks`, démarrage du serveur (`ready_timeout`), ouverture, remplissage et
clic dans le navigateur. L’instantané pris juste après le clic ne montrait pas encore
l’élément ajouté (le serveur n’a journalisé aucune erreur) : la persistance via
l’interface n’a donc pas été vérifiée par cet essai. L’isolation réelle Docker (`AGENTASE_TEST_SANDBOX=docker`) passe. Les tests
historiques en échec (`test_api_wiring`, `test_database_runtime`, `test_compiler`,
`test_portability`) échouent à l’identique sur la référence figée. Aucun run avec un
vrai modèle ni score Arcbench nouveau n’est revendiqué ; `main.py` reste l’ancien
pipeline jusqu’à l’étape 20.


## État de la partie C

Les étapes 13 à 18 sont implémentées le 15 novembre 2026 dans `infrastructure/verification/`
et `infrastructure/runtime/budget.py`. `ApplicationAgent.generate()` enchaîne travail de
l’agent, vérification hôte et réparations dans une seule session ; `main.py` reste l’ancien
pipeline jusqu’à l’étape 20.

- **13 — contrôles de l’application réelle** (`results.py`, `checks.py`) : `verify_application`
  (typecheck, build, tests backend avec fichiers choisis), `http_request`, `database_query` et
  le navigateur opèrent sur l’application elle-même. Les statuts distinguent `passed`, `failed`,
  `missing`, `no_tests_executed`, `incomplete` (tests ignorés), `environment_error`.
- **14 — acceptation indépendante** (`acceptance.py`, `verifier.py`) : la suite vit dans un
  dossier de l’hôte, hors du workspace. Elle reprend les tests externes fournis
  (`input/tests`), jamais modifiés ni relus, et ne génère des tests Playwright que pour les
  scénarios sans test indépendant, à partir de l’exigence d’origine. Les interfaces observées
  (pages déclarées par `interface_write`, instantanés d’accessibilité) servent à localiser,
  pas à définir l’attendu. La revue d’un test généré a lieu une fois par preuve d’échec et
  doit s’appuyer sur l’exigence ou l’environnement. Aucune IR n’est lue.
- **15 — couverture et fidélité visuelle** (`coverage.py`, `visual.py`) : un registre par
  scénario sépare déclarations de l’agent et vérification hôte, liste les aspects requis
  (rejet, état vide, données distinctes, rafraîchissement) et passe à `stale` toute preuve
  obtenue sur une autre révision des sources. Le visuel est une dimension distincte :
  comparaison déterministe structure/couleur/proportions avec la référence, ressources
  cassées, revue optionnelle par le modèle visuel ; `missing_interface` et `unavailable`
  restent explicites.
- **16 — finalisation et réparation** (`driver.py`) : une réponse finale est une proposition.
  Issues distinctes : `accepted`, `failed`, `provider_error`, `environment_error`,
  `interrupted`, `budget_exceeded`, `verification_missing`. Un échec réparable revient dans la
  même conversation (symptômes, identifiants d’exigences, artefacts de preuve, sans le code
  des tests).
- **17 — budget et stagnation** (`budget.py`) : durée totale avec réserve pour la vérification
  finale, requêtes par catégorie (principal, fallback visuel, génération d’acceptation, revue
  de test, revue visuelle), appels d’outils, tokens déclarés (entrée + sortie, sans recompter
  cache ni raisonnement), retries connus du SDK. Un appel identique au résultat identique
  reçoit une réorientation puis arrête le tour ; les mêmes échecs d’acceptation sans
  changement de source arrêtent la réparation. Une réponse tronquée est poursuivie, jamais
  comptée comme terminée. Les valeurs du profil (250 requêtes, 5 400 s dont 900 s réservées,
  12 M tokens) sont des valeurs initiales dérivées de la référence, à réviser à l’étape 23.
- **18 — coût des vérifications** : étapes rapides d’abord (intégrité, dépendances, build,
  démarrage, tests) ; un tour incrémental réutilise dépendances et build tant que sources,
  outils, image et génération du miroir sont inchangés, donne une base neuve au serveur et
  rejoue d’abord les fichiers en échec. Le succès n’est déclaré qu’après un tour propre :
  miroir remis aux seules sources livrées, reconstruction, démarrage comme en déploiement,
  suite complète.

Défauts corrigés au passage : un fichier supprimé du workspace survivait dans le miroir
d’exécution ; chaque appel d’outil recalculait plusieurs fois l’empreinte de tout le
workspace (cache par signature de répertoire, désactivé pour les fichiers modifiés depuis
moins de deux secondes).

Limites connues :

- le runner Playwright et les tests d’acceptation s’exécutent sur l’hôte (Node requis), hors
  sandbox, avec un environnement nettoyé ; l’application, elle, reste dans la sandbox ;
- le tour propre conserve `node_modules` (`acceptance.clean_install: true` pour réinstaller) ;
- sans IR, l’invalidation des preuves est globale : tout changement de source les périme ;
- le seuil visuel déterministe (0,6) est une heuristique non calibrée sur des cas réels ;
- la présence d’assertions dans un test qui passe n’est pas prouvée, seulement son exécution.

Validation : 32 tests hors ligne (`test_agent_verification.py`, `test_agent_finalization.py`)
avec une application et un runner simulés ; un test d’intégration réel
(`AGENTASE_TEST_ACCEPTANCE=1`) où Playwright et Chromium détectent une règle métier fausse
sur un vrai serveur HTTP ; un essai de bout en bout scripté (modèle simulé, sandbox Docker
`node:22-bookworm`, Playwright réel) où l’agent propose une application dont la liste
n’affiche pas les titres : échec d’acceptation au tour 1, retour dans la même session,
correction, tour incrémental candidat puis tour propre accepté (3 tours, 8 requêtes, 470 s
dont 260 s d’installation npm). Cet essai a révélé et fait corriger un plantage du contrôle
de réutilisation des dépendances sous Windows (liens npm du conteneur illisibles depuis
l’hôte). Aucun run avec un vrai modèle ni score Arcbench n’est revendiqué.


## État de la partie D

Les étapes 19 à 22 sont réalisées le 16 novembre 2026. Le pipeline à 13 passes n’existe
plus dans le dépôt : `main.py` lance une session d’agent, et aucun repli vers l’ancien
moteur n’est prévu (la référence figée `benchmarks/baseline/compiler.zip` sert aux
comparaisons).

- **19 — reprise et traçabilité** (`runtime/persistence.py`) : chaque run possède son dossier
  `ÉTAT/SESSION/` avec `session.json` (format versionné, écriture atomique, version
  précédente conservée et relue si la dernière écriture est tronquée), `events.jsonl`
  (lignes incomplètes ignorées) et `run-summary.json`. Les empreintes des entrées, du profil
  et du workspace sont enregistrées ; `--resume` est refusé si les entrées ou les
  instructions du profil ont changé, et relever une limite de budget n’est pas un
  changement. La reprise ne restaure aucun fichier : l’agent est averti qu’une commande
  interrompue a pu avoir un effet partiel et que le workspace peut différer. Les états de
  fichiers sont des commits Git distincts créés après chaque vérification. Les secrets
  connus et les chaînes en forme d’identifiants sont masqués avant écriture. Deux runs ne
  partagent ni session, ni miroir, ni processus.
- **20 — bascule du point d’entrée** : `main.py INPUT --output-dir OUTPUT --port PORT`
  conserve ses arguments et `--model-log`, et ajoute `--profile`, `--resume`, `--state-dir`,
  `--max-requests`, `--max-seconds`, `--sandbox` ainsi que les diagnostics hors ligne. La
  configuration, la clé, la reprise et le backend d’exécution sont validés avant toute
  requête payante. Rapport dans `OUTPUT/.arc/run.json` ; codes de sortie 0 (accepté),
  130 (interrompu), 1 (autre issue), 2 (configuration). `Compiler` est supprimé.
- **21 — nettoyage** : suppression des scripts `00` à `12`, de `infrastructure/compiler.py`,
  `stages/`, `shared/agent`, `shared/models`, `shared/rag`, `utils/presentation`, `utils/cli.py`,
  des scripts d’analyse de l’ancien journal et des 30 fichiers de tests de l’ancien pipeline.
  `normalize.py` est déplacé dans `infrastructure/requirements/`. La dépendance `rich`,
  devenue inutile, est retirée. Deux garanties d’anciens tests sont reprises sur le nouveau
  contrat (fins de ligne CRLF, réduction des grandes images). README et carte du code
  réécrits ; `principle.md` et `IDEES_AMELIORATION_AGENT.md` portent un bandeau historique.
- **22 — packaging** : l’archive contient le moteur, les profils, les templates et les tests ;
  elle refuse un script numéroté, un import LingCore ou un fichier contenant une clé de
  `.env`, et livre un `.env` à clé vide.

Ajout hors plan, à connaître : un backend d’exécution `host` (`--sandbox host`). Il n’est
jamais choisi par `auto` et n’est pas un repli : c’est un choix explicite pour une machine
elle-même jetable, sans Docker ni Bubblewrap. Les commandes s’y exécutent dans le miroir de
la session avec un environnement nettoyé, **sans isolation**. Sans lui, un runner dépourvu
de sandbox rend `environment_error` avant toute requête.

Validation : 100 tests hors ligne passent (2 d’intégration optionnels ignorés par défaut).
L’archive a été extraite dans un dossier vierge, installée avec `uv sync`, puis sa CLI
publique a été exécutée de bout en bout contre un fournisseur de modèle simulé local
(protocole HTTP réel, aucune requête payante), avec la sandbox Docker et Playwright réels :
application d’abord défectueuse, refusée par l’acceptation, corrigée dans la même session,
acceptée depuis un état propre (code 0, 6 requêtes, 3 tours, 494 s) ; ni `dist/`, ni base
locale, ni ancienne IR dans la sortie. **Aucun run avec le vrai modèle n’a été effectué.**

Points à vérifier avant une soumission Arcbench :

- l’environnement du runner : s’il n’offre ni Docker ni Bubblewrap, soumettre avec
  `--sandbox host` (ou un profil `execution.backend: host`) ; Node.js y est requis pour les
  tests d’acceptation ;
- `MAX_OUTPUT_TOKENS` : le `.env` local est recopié dans l’archive ; l’ancien pipeline
  utilisait 320 000, valeur que le nouveau moteur envoie telle quelle comme
  `max_completion_tokens`. Le profil prévoit 16 384 ;
- la compatibilité réelle de l’endpoint avec les appels d’outils natifs (`--probe`), toujours
  non vérifiée (case ouverte de l’étape 04).

## État de la partie E

L’étape 23 demande des runs réels payants et des résultats Arcbench externes : ils ne sont
pas exécutés. Ce qui existe est l’outillage, vérifié hors ligne et sur un run réel de la CLI :

- `scripts/evaluate.py` : plan apparié (mêmes cas, ordre des variantes alterné à chaque
  répétition, workspace et état neufs par run), fiche par run conforme à
  `benchmarks/PROTOCOL.md`, écrite immédiatement y compris pour les échecs, interruptions et
  dépassements de délai ; rattachement des résultats externes ; rapport par variante et par
  paire. Les tokens d’entrée et de sortie sont les seuls totaux ; cache et raisonnement
  sont des sous-totaux jamais ré-additionnés ; les requêtes sans usage et les retries connus
  sont comptés à part, et un coût n’est calculé que si tout l’usage est connu. Temps
  jusqu’au premier parcours utilisable et temps de réparation sont extraits de l’état.
  Les faux succès locaux et les paires où le candidat consomme davantage sont listés.
- `benchmarks/criteria.json` : perte de qualité maximale et gains minimaux **proposés**,
  marqués `confirmed: false`. Tant qu’ils ne sont pas confirmés avant les runs, ou que trop
  peu de paires ont un résultat externe, le rapport répond `insufficient_evidence`.
- `benchmarks/variants.json` : référence figée, agent, et deux ablations.

Étape 24 : aucune optimisation n’est retenue, faute de mesure. Deux mécanismes sont
implémentés comme variantes désactivées par défaut, chacune ajoutant un seul élément au
profil de base afin de permettre l’ablation :

- `variant-skills.yaml` : quatre guides courts (SQL, HTTP, React, Playwright) lus à la
  demande par `read_skill`. Leur contenu vient du template et des tests fournis, pas
  d’erreurs observées sur de vrais runs, qui n’existent pas encore ;
- `variant-symbols.yaml` : `find_symbol`, recherche textuelle des définitions et usages
  (fonctions, types, tables SQL, routes).

Non implémentés, volontairement : la parallélisation des lectures (les outils de lecture
sont synchrones et locaux, le gain attendu est nul), la mémoire de corrections entre
applications, le routage de modèles et la délégation externe. Chacun exige d’abord la
comparaison à modèle constant de l’étape 23.


## 4. Ordre de réalisation

Les cases cochées indiquent les éléments réalisés ; les validations externes et les étapes suivantes restent ouvertes.

### Étape 01 — Figer la référence et le protocole de comparaison

- [x] Identifier une révision et une archive du compilateur actuel, leurs configurations et leurs dépendances.
- [x] Enregistrer l’empreinte et la version de l’archive LingCore étudiée, ainsi que la révision de notre moteur pour chaque essai.
- [ ] Conserver les rapports, sorties et durées des runs de référence.
- [x] Définir un jeu de développement varié et une validation réservée : authentification, CRUD, filtres, relations, états vides, erreurs, navigation et présentation.
- [ ] Comparer ancien moteur et nouvel agent à modèle, paramètres, ressources et budgets comparables ; comparer aussi au profil LingCore connu pour bien fonctionner lorsque sa configuration est disponible.
- [x] Compter les échecs, interruptions et dépassements dans les résultats.

**Livrable :** manifeste de référence et protocole reproductible. Les anciennes révisions servent aux comparaisons hors du nouveau chemin de production.

**Validation :** chaque résultat est rattaché à un cas, un artefact, un modèle et une configuration précis. Aucun accès aux tests cachés n’est nécessaire pour développer le système.

### Étape 02 — Définir les contrats du moteur et préparer ses dépendances

- [x] Créer les types locaux `Message`, `ToolCall`, `ToolResult`, `ModelResponse`, `Usage` et `AgentEvent`, avec identifiants d’appels et validation des arguments.
- [x] Définir une interface de client modèle indépendante du SDK : messages et schémas d’outils en entrée, texte, appels, usage et raison de fin en sortie.
- [x] Définir un registre d’outils et un contexte d’exécution propres au projet : workspace, capacités autorisées et état de la session.
- [x] Implémenter un premier client compatible OpenAI avec le SDK déjà utilisé ; conserver le client JSON historique pour le pipeline tant que la bascule n’a pas eu lieu.
- [x] Ajouter un client simulé déterministe pour tester des conversations sans réseau ni facturation.
- [x] Réutiliser les dépendances actuelles ; ajouter un package seulement si une capacité implémentée le nécessite. Les versions de Rich et Playwright de LingCore ne créent aucun conflit puisqu’il n’est pas installé.
- [x] Maintenir la cohérence de `pyproject.toml`, `requirements.txt` et `uv.lock` ; vérifier l’installation depuis un environnement propre.

**Fichiers proposés :** `infrastructure/runtime/messages.py`, `events.py`, `model.py`, `tools.py`, et les manifestes si nécessaire.

**Validation :** les messages et résultats d’outils passent un aller-retour de sérialisation ; le client simulé et le premier client fournisseur respectent le même contrat. Aucun import ni artefact LingCore n’est requis.

### Étape 03 — Implémenter la boucle et la session de notre moteur

- [x] Introduire `ApplicationAgent` comme point d’entrée et une boucle locale dans `runtime/loop.py`, indépendants des scripts numérotés.
- [x] Fixer explicitement le workspace au dossier de sortie demandé et créer un identifiant de session unique.
- [x] Conserver en mémoire la conversation : demande, réponse du modèle, appels d’outils et observations identifiées. Une correction ultérieure utilise la même session.
- [x] Exécuter la boucle « appeler le modèle → valider les appels → exécuter les outils → ajouter les observations → recommencer » ; une réponse sans outil produit une proposition de fin.
- [x] Adapter les exécuteurs de lecture et d’édition existants au registre local pour une première tâche réelle ; vérifier leur effet avec une lecture ultérieure.
- [x] Retourner les erreurs d’arguments ou d’outil comme observations exploitables ; distinguer les erreurs terminales du fournisseur et les sorties tronquées.
- [x] Ajouter dès le noyau une limite configurable de requêtes et une annulation propre. La comptabilité globale et la stratégie de stagnation seront étendues à l’étape 17.
- [x] Émettre des événements locaux de texte, début/fin d’outil, usage, erreur et fin de tour. Fermer les ressources explicitement à la fin de la session.
- [x] Définir l’emplacement futur de l’état persistant séparément du code applicatif ; la reprise sur disque relève de l’étape 19.

**Fichiers proposés :** `infrastructure/application_agent.py`, `infrastructure/runtime/loop.py`, `infrastructure/runtime/state.py`.

**Validation :** avec un modèle simulé, une tâche lit puis édite un fichier, vérifie la modification et reçoit une correction dans la même conversation. Tester aussi un outil invalide, la limite de requêtes, l’annulation et l’isolation de deux sessions. Aucun import de LingCore, `Compiler`, `propose_json()` ou `run_file_agent()`.

### Étape 04 — Créer un profil dédié à la génération d’applications

- [x] Ajouter `profiles/arcbench-app/config.yaml`, `role.md` et `workflow.md`.
- [x] Implémenter notre chargeur de profil et son assemblage des instructions : validation des clés, chemins relatifs au profil, paramètres de modèle et outils autorisés. Le format appartient au projet ; il n’a pas à être compatible avec le chargeur LingCore.
- [x] Configurer explicitement modèle, fournisseur, raisonnement, modalités, retries et mémoire. Ne pas hériter implicitement de l’endpoint ou du modèle du profil coding fourni par LingCore.
- [x] Conserver la compatibilité des variables `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MODEL` et des réglages visuels utiles, avec une règle de priorité documentée.
- [x] Décrire un objectif observable : application complète respectant les exigences, construite et vérifiée.
- [x] Donner des habitudes de travail courtes : explorer avant une décision importante, planifier si nécessaire, réaliser des parcours utilisables, vérifier les changements et traiter les erreurs à leur source.
- [x] Limiter le premier profil aux capacités déjà implémentées ; rejeter une capacité demandée mais indisponible. Ajouter navigateur, skills et autres extensions à leurs étapes respectives.
- [ ] Vérifier les capacités réelles de l’endpoint : outils natifs, streaming, images, usage et cache. Un fournisseur incompatible doit être diagnostiqué explicitement.

**Fichiers proposés :** `infrastructure/runtime/config.py`, `composer.py` et `profiles/arcbench-app/`.

**Vérification fournisseur :** ajouter des tests de contrat avec réponses simulées et une sonde explicite pour les essais réels autorisés. La configuration seule ne prouve pas la compatibilité de l’endpoint ; consigner les capacités non vérifiées. Seules les capacités effectivement utilisées sont nécessaires au premier essai.

**Validation :** le profil ne prescrit aucun ordre « schéma → obligations → API → UI → triggers » et n’exige pas un document de conception pour chaque couche.

### Étape 05 — Préparer les exigences sans analyse LLM obligatoire

- [x] Charger et valider le YAML localement ; détecter identifiants dupliqués, références invalides et ressources manquantes.
- [x] Préserver le texte, les scénarios, les contraintes parentes et les exigences portées par des nœuds non feuilles.
- [x] Produire un catalogue léger : identifiant, titre, source, parent, scénarios et ressources associées.
- [x] Fournir les petites spécifications intégralement ; pour les grandes, permettre des lectures exactes par identifiant et conserver un inventaire de couverture global.
- [x] Exposer les références visuelles à l’agent, avec lecture native ou fallback adapté au modèle.
- [x] Supprimer l’obligation de faire analyser toutes les images dès le démarrage. Observer d’abord les ressources utiles au travail courant ; enregistrer ce qui a réellement été consulté.

**À extraire :** `stages/requirements/normalize.py`, parties utiles de `tree.py`, chargement des ressources.

**Validation :** tests déterministes du catalogue, des doublons, références, ressources, scénarios parents et consultation visuelle ; aucune requête modèle au chargement.

### Étape 06 — Découpler le squelette applicatif des passes

- [x] Réutiliser `initialize_project()` pour créer seulement les fichiers manquants.
- [x] Retirer dans les templates les commentaires et comportements qui attendent les étapes `05` ou `08`.
- [x] Permettre à l’agent de maintenir directement `tableFiles`, `seedFiles`, le registre des API, les routes et les composants.
- [x] Exposer les fichiers de base de données et la configuration applicative nécessaires à l’implémentation ; ne pas reprendre les restrictions qui réservent leur modification aux anciennes passes.
- [x] Conserver les contraintes techniques utiles : clés étrangères, initialisation reproductible, copie des ressources SQL et séparation des données de test.
- [x] Remplacer les messages du type « run step 08 first » par des diagnostics adaptés au nouveau moteur.

**Fichiers :** `shared/project/initialize.py`, `shared/project/templates/`, notamment `db/initialize.ts`, `db/seed.ts`, `api/register.ts` et `scripts/test-api.mjs`.

**Validation :** tests d’initialisation idempotente, préservation des fichiers existants, scripts build/test racine et templates DB sans IR préalable.

### Étape 07 — Installer les dépendances au moment utile

- [x] Centraliser l’installation npm au niveau du workspace.
- [x] Utiliser le lockfile lorsqu’il existe et invalider l’état d’installation quand les manifestes ou l’environnement changent.
- [x] Ne pas relancer l’installation parce qu’une nouvelle tâche ou une nouvelle couche commence.
- [x] Déclarer les outils réellement disponibles dans l’environnement : Node, npm, Python, navigateur et bibliothèques natives.
- [x] Préparer l’environnement navigateur une fois, avec des diagnostics d’installation distincts des défauts applicatifs.

**Fichiers :** `shared/project/dependencies.py`, préparation du runner et scripts du template.

**Validation :** tests de cache, lockfile, changement de manifeste, suppression de `node_modules` et changement d’environnement.

### Étape 08 — Étendre notre registre d’outils

- [x] Activer les outils de lecture, listing, recherche, écriture, édition, patch, Git en lecture seule et suivi des tâches adaptés au profil.
- [x] Retirer du chemin nominal `context_request`, les appels plats dans un objet JSON et les consignes interdisant les outils natifs.
- [x] Ajouter des outils locaux pour lire une exigence exacte, obtenir la couverture courante et demander une vérification de l’application. Les enregistrer explicitement avec leurs schémas et droits.
- [x] Garder les schémas d’outils concis ; ne pas envoyer un catalogue de capacités inutilisées.
- [x] Tester les patches multiples et les refus d’écriture utiles ; autoriser une réécriture justifiée d’un fichier applicatif tout en protégeant les exigences et l’acceptation.
- [x] Conserver le texte libre pour les diagnostics et plans ; réserver JSON aux véritables données structurées.

**Contrat d’extension :** un outil reçoit un contexte de session explicite, valide ses arguments et renvoie un résultat ou une erreur structurée. Un registre local suffit à cette étape ; un système complet de plugins n’est pas un prérequis.

**Validation :** tests de recherche, lecture paginée, artefacts, patch atomique, refus de fichiers protégés et réécriture avec empreinte.

### Étape 09 — Définir l’environnement d’exécution sans interaction

- [x] Définir les capacités autorisées avant le lancement : workspace, commandes, réseau, processus et accès navigateur.
- [x] Implémenter et tester un exécuteur adapté à chaque environnement visé, en réutilisant nos utilitaires de processus. Étudier les backends de LingCore pour concevoir l’isolation appropriée ; Bubblewrap ne convient pas à Windows natif.
- [x] Fournir une configuration locale Windows et une configuration pour l’environnement Arcbench, avec diagnostics explicites si le backend prévu manque.
- [x] Traiter l’installation des dépendances, les commandes applicatives et l’accès navigateur selon leurs besoins réseau réels.
- [x] Ne jamais attendre une confirmation interactive dans un run de benchmark.
- [x] Protéger les exigences et tests d’acceptation aussi contre le shell, les scripts et les liens de fichiers ; un refus dans `edit_file` seul ne suffit pas.
- [x] Limiter l’accès aux fichiers privés et variables d’environnement aux besoins de l’exécution.

**Contrat d’exécution :** notre politique non interactive applique les capacités autorisées avant chaque action. Une autorisation logique ne remplace pas l’isolation du système de fichiers, des processus et du réseau.

**Validation :** tests d’isolation miroir, variables nettoyées, timeout, annulation, nettoyage des processus et diagnostic d’un backend absent.

### Étape 10 — Donner accès au navigateur et aux processus persistants

- [x] Implémenter nos outils navigateur avec Playwright et nos outils de processus à partir des utilitaires existants ; étudier les modules `browser` et `process` de LingCore comme références.
- [x] Réutiliser un serveur de développement pendant les corrections ; vérifier son état et ses logs avant de le redémarrer.
- [x] Donner accès aux snapshots DOM, captures, interactions, erreurs console et requêtes réseau pertinentes.
- [x] Rendre accessibles les ports nécessaires au navigateur tout en conservant la politique réseau choisie.
- [x] Redémarrer le backend lorsque les modifications le demandent ; vérifier que le navigateur observe bien la dernière version.
- [x] Conserver des captures et traces sur les échecs significatifs, avec lecture ciblée des détails.

**Validation :** test proxy et tests de cycle de vie présents ; le parcours Chromium réel reste dépendant de l’installation/sandbox de l’hôte.

### Étape 11 — Composer un contexte stable et économique

- [x] Séparer instructions stables, objectif utilisateur, observations et éventuelles notes de conception.
- [x] Envoyer une fois les informations initiales nécessaires ; ne pas réinjecter tout le catalogue, toutes les sources et les rapports complets après chaque modification.
- [x] Utiliser les outils paginés pour les détails et déporter les grandes sorties dans des fichiers consultables.
- [x] Retenir les lectures utiles et invalider leurs versions après modification.
- [x] Implémenter une fenêtre de contexte et une compaction inspirées de LingCore ; conserver exigences non terminées, contrats effectivement adoptés, causes établies et prochaines vérifications. Mesurer le coût des résumés et préserver les paires appels/résultats.
- [x] Stabiliser l’ordre des contenus et activer les options de cache compatibles avec le fournisseur. Mesurer leur effet réel.

**Validation :** tests de contexte borné, artefacts paginés, compaction sans appel modèle, conservation des paires outil/résultat et invalidation des lectures.

### Étape 12 — Réaliser les fonctionnalités sans découpage par couche imposé

- [x] Donner à l’agent un objectif global et un inventaire des exigences, avec `todo_write` pour un plan modifiable.
- [x] Autoriser un premier parcours utilisable puis des incréments cohérents ; laisser l’agent choisir leur ordre selon les dépendances réelles.
- [x] Autoriser dans une même tâche les changements SQL, API, état frontend, composants, styles et navigation.
- [x] Permettre une courte note de contrat quand plusieurs composants en dépendent, sans imposer une IR exhaustive.
- [x] Conserver les contraintes transversales : identité, permissions, messages, données de démarrage, persistance et comportements déjà validés.
- [x] Éviter la création d’un appel de conception et d’un appel de revue pour chaque petite décision.

**Validation :** tests de boucle multi-outils et corrections dans une session unique ; aucun ordre de couches ni artefact IR n’est requis.

### Étape 13 — Remplacer les tests pilotés par IR par des contrôles de l’application réelle

- [x] Extraire les runners utiles de `backend/testing.py`, `frontend/ui/testing.py` et `triggers/testing.py`.
- [x] Les faire fonctionner avec des chemins de tests, commandes et interfaces observées, sans dépendance obligatoire aux anciens artefacts.
- [x] Exposer des contrôles ciblés : compilation TypeScript, tests locaux, requête HTTP, inspection de base et scénario navigateur.
- [x] Garder les tests écrits par l’agent comme outils de développement ; choisir leur granularité selon le risque et la complexité.
- [x] Retirer l’obligation de générer d’abord une suite TDD par API, une suite de présence par page et une suite de triggers pour toute fonctionnalité.
- [x] Remplacer les états de test artificiels et le runtime UI intermédiaire par l’état réel de l’application pour la validation fonctionnelle finale.
- [x] Vérifier que les commandes de test exécutent réellement des assertions ; distinguer absence de tests, succès et vérification non applicable.

**Validation :** les contrôles détectent des défauts réels sans exiger un DOM ou une architecture interne uniquement issus de l’ancien compilateur.

### Étape 14 — Découpler l’acceptation indépendante des anciennes représentations

- [x] Réécrire l’assemblage actuel de `acceptance_task()`, qui utilise encore schéma, API, UI et design des triggers.
- [x] Partir des exigences d’origine, scénarios, ressources, contraintes parentes et données initiales.
- [x] Découvrir seulement les interfaces nécessaires : URL, nom accessible, route HTTP, schéma réellement utilisé pour préparer des fixtures valides.
- [x] Distinguer interfaces observées et attentes : l’application observée ne définit pas le comportement correct.
- [x] Utiliser les tests externes fournis quand ils existent ; générer au plus les contrôles supplémentaires nécessaires à la couverture manquante, puis conserver leur version.
- [x] Éviter une génération supplémentaire de tests lorsqu’un même résultat est déjà vérifié de manière indépendante.
- [x] Isoler les tests, leurs fixtures et leur configuration du workspace modifiable par l’agent.
- [x] Limiter la revue d’un test aux erreurs étayées par l’exigence ou l’environnement ; aucune adaptation aux seules sorties incorrectes de l’application.

**Validation :** le runner d’acceptation fonctionne sans `db_schema.json`, `backend_apis.json`, `ui_design.json` ni `frontend_triggers.json`. Des mutations métier volontairement fausses sont détectées.

### Étape 15 — Suivre la couverture et la fidélité visuelle sans IR exhaustive

- [x] Maintenir un registre léger par exigence/scénario : état, preuve de vérification, version de source et dernier résultat.
- [x] Séparer les éléments déclarés implémentés par l’agent des éléments effectivement vérifiés par l’hôte.
- [x] Inclure les cas de rejet, les états vides, les données distinctes et le rafraîchissement lorsque les exigences le demandent.
- [x] Fournir les références visuelles originales et confronter les captures réelles aux pages attendues : structure, proportions, ressources, texte et dimensions pertinentes.
- [x] Distinguer conformité fonctionnelle et visuelle ; conserver un statut explicite si une preuve requise n’a pas pu être obtenue.
- [x] Invalider les preuves affectées après modification au lieu de garder un statut « vérifié » périmé.

**Validation :** le registre met en évidence les omissions, et un écran visuellement incorrect ne devient pas conforme parce que les boutons existent.

### Étape 16 — Construire le driver de finalisation et de réparation

- [x] Traiter une réponse finale de notre moteur comme une proposition de fin de travail.
- [x] Déclencher les vérifications obligatoires côté hôte ; leur résultat décide du succès applicatif.
- [x] En cas d’échec réparable, ajouter un retour compact avec symptômes, attentes et preuves dans la même session.
- [x] Laisser l’agent rechercher la cause dans toutes les couches applicatives et modifier les contrats locaux nécessaires.
- [x] Préserver le budget total, les compteurs et les processus utiles entre les réparations.
- [x] Distinguer succès, échec fonctionnel, panne fournisseur, problème d’environnement, interruption, budget dépassé et vérification manquante.

**Cycle de vie à implémenter :** une fin de tour laisse la session ouverte pour recevoir les résultats de vérification. La fermeture de la session nettoie ses processus, navigateur et client modèle. Tester ces transitions, y compris après annulation ou erreur, sans dépendre du driver de LingCore.

**Validation :** l’agent peut annoncer avoir terminé, recevoir un vrai échec d’acceptation, le corriger et être vérifié de nouveau sans nouvelle conversation ni remise à zéro du budget.

### Étape 17 — Borner les répétitions et le coût réel

- [x] Développer un gestionnaire de budget local, inspiré de `ExecutionBudget`, pour la durée, les requêtes, les outils et les tokens déclarés ; étendre les limites du noyau et fixer les valeurs par profil à partir des runs de référence.
- [x] Compter explicitement les vérifications, résumés, fallbacks visuels, retries et éventuelles revues.
- [x] Détecter les mêmes lectures, erreurs et patches répétés sans changement utile.
- [x] En cas de stagnation, demander une preuve différente, élargir la zone inspectée ou changer une hypothèse. Une hausse de raisonnement ou un changement de modèle reste une variante mesurée.
- [x] Réserver une partie du temps à la construction et à la vérification finale ; ne pas copier mécaniquement le plafond de 100 itérations du profil coding.
- [x] Rendre les erreurs de fournisseur et limites de sortie explicites ; ne pas reclasser une réponse tronquée en succès.

**Validation :** les boucles injectées sont arrêtées ou réorientées ; les tâches qui progressent conservent une possibilité raisonnable d’aboutir.

### Étape 18 — Réduire le coût des vérifications sans les affaiblir

- [x] Lancer d’abord les contrôles rapides et les tests affectés par le changement.
- [x] Rejouer plus largement après une modification transversale ou un point de stabilisation.
- [x] Réutiliser serveur, navigateur et dépendances tant que leur état est valide.
- [x] Mettre en cache un contrôle uniquement à partir de toutes ses dépendances pertinentes : sources, configuration, scripts, lockfile, versions des outils, environnement et état de données si nécessaire.
- [x] Ne pas conserver un résultat fonctionnel à partir de la seule empreinte du fichier de test.
- [x] Effectuer la validation de livraison depuis un état propre même lorsque des contrôles intermédiaires ont été réutilisés.

**Validation :** les corrections locales évitent les reconstructions inutiles et une modification indirecte invalide bien les contrôles concernés.

### Étape 19 — Ajouter la reprise et une traçabilité compacte

- [x] Implémenter la persistance de nos sessions, événements et usages par run, avec identifiants stables, format versionné et écritures atomiques. Prévoir la récupération après une écriture interrompue.
- [x] Enregistrer les empreintes des sources d’entrée, du profil, du workspace et des preuves d’acceptation.
- [x] Ajouter une option de reprise contrôlée ; refuser ou revalider un état dont les entrées ont changé.
- [x] Ne pas confondre reprise conversationnelle et restauration des fichiers : enregistrer explicitement les points de reprise du workspace.
- [x] Ne pas supposer qu’une annulation du tour annule les effets déjà produits par un shell ou une écriture de fichier.
- [x] Produire un résumé de métriques par run ; conserver les détails volumineux à part, avec masquage des secrets.
- [x] Créer un état neuf pour chaque cas de benchmark, sans mémoire de travail ni processus hérités d’un autre cas.

**Validation :** une interruption peut reprendre de façon cohérente ; deux cas indépendants ne se transmettent pas leur état métier.

### Étape 20 — Basculer le point d’entrée et supprimer les appels aux passes

- [x] Modifier `main.py` pour construire le profil, préparer les entrées puis lancer `ApplicationAgent`.
- [x] Remplacer `Compiler.compile()` par l’appel à `ApplicationAgent` ou retirer cette classe si elle n’a plus de consommateur utile.
- [x] Conserver `INPUT`, `--output-dir`, `--port` et les options de logs nécessaires aux appelants existants.
- [x] Ajouter les options de profil, reprise et limites globales retenues ; valider leur compatibilité avant tout appel coûteux.
- [x] Retirer les messages « stage 00…12 » et produire un rapport de run avec statut applicatif et cause éventuelle d’échec.
- [x] Conserver les codes de sortie utiles : succès vérifié, échec, interruption. Les échecs fonctionnels rendent déjà un code non nul dans le code actuel : préserver ce comportement.
- [x] Ne prévoir aucun fallback automatique vers les anciennes passes. La révision de référence suffit pour comparer ou revenir en arrière pendant le développement.

**Validation :** un lancement normal ne charge aucun script numéroté et ne génère aucune ancienne IR par obligation.

### Étape 21 — Nettoyer les modules, les tests et les documents devenus obsolètes

- [x] Déplacer les helpers encore utilisés vers des modules indépendants avant de retirer leurs anciens orchestrateurs.
- [x] Supprimer les scripts `00` à `12` lorsque le nouveau chemin couvre les besoins conservés.
- [x] Supprimer les prompts, index et règles d’édition uniquement nécessaires aux anciennes IR et à leurs propriétaires de passes.
- [x] Adapter les tests qui figent l’ancien ordre, les prompts ou les empreintes du baseline ; conserver leurs garanties métier utiles sous des tests du nouveau contrat.
- [x] Remplacer les tests imposant une sortie intermédiaire par des tests d’outils, de cycle de vie, d’isolation, de couverture et d’acceptation.
- [x] Mettre à jour `README.md`, la carte du code et `principle.md` pour présenter le moteur réellement livré.
- [x] Marquer l’ancien catalogue d’améliorations comme historique ; conserver les rapports et applications générées comme artefacts de comparaison hors du runtime.

**Validation :** les imports de production, tests actifs et instructions de lancement ne dépendent plus du pipeline retiré.

### Étape 22 — Adapter le packaging et tester l’artefact livré

- [x] Modifier `scripts/package.py` : retirer l’énumération obligatoire des scripts numérotés et les sources spécifiques devenues inutiles.
- [x] Retirer du manifeste requis `01_explore_requirement.py`, `12_implement_frontend_tdd.py` et les autres fichiers qui ne sont plus nécessaires au nouveau moteur.
- [x] Inclure les sources de notre moteur, les profils, outils et ressources nécessaires à une installation propre, avec les dépendances déclarées.
- [x] Vérifier les chemins relatifs après extraction et l’absence d’import ou de dépendance LingCore ; ne pas dépendre de `.comparison/` ou de fichiers ignorés locaux.
- [x] Définir comment les secrets sont fournis ; ne pas embarquer de clés API.
- [x] Extraire l’archive dans un dossier vierge, installer selon les contraintes réelles du runner et exécuter la CLI publique.
- [x] Vérifier construction, initialisation des données, démarrage et parcours sur l’application extraite, avec absence d’anciens `dist/` ou bases locales.

**Validation :** l’archive soumise est autonome dans l’environnement prévu et contient les sources correspondant aux résultats mesurés.

### Étape 23 — Évaluer le nouveau moteur avant les optimisations supplémentaires

- [ ] Exécuter des comparaisons appariées sur les mêmes tâches, avec plusieurs runs lorsque possible.
- [ ] Mesurer score externe, exigences satisfaites, faux succès locaux, tokens, durée et dépenses disponibles.
- [ ] Mesurer le temps jusqu’au premier parcours utilisable et le temps de réparation après son premier échec.
- [x] Distinguer usage déclaré, retries connus et requêtes dont l’usage est indisponible.
- [x] Ne pas additionner deux fois les tokens : les tokens en cache peuvent être inclus dans l’entrée et le raisonnement dans la sortie selon les champs du fournisseur.
- [ ] Établir avant l’essai les pertes de qualité inacceptables et le gain minimal utile en coût ou durée.
- [ ] Conserver et analyser les cas où l’agent libre consomme davantage que l’ancien moteur.

**Validation :** décision fondée sur les artefacts livrés et les résultats externes, avec limites de la mesure explicites. La suppression des passes n’est pas considérée comme une preuve de gain.

### Étape 24 — Optimiser ensuite uniquement les mécanismes utiles

Réaliser des expériences séparées et retenir celles qui améliorent les mesures précédentes :

- [ ] Petits skills SQL, React, HTTP et Playwright sélectionnés selon la tâche, issus des erreurs observées.
- [ ] Recherche de symboles et dépendances avant ajout d’un index sémantique ; embeddings et reranking seulement si les échecs de récupération le justifient.
- [ ] Mémoire de corrections validées, avec conditions d’application et invalidation, distincte de la mémoire d’une application.
- [ ] Parallélisation des lectures et vérifications indépendantes ; coordonner les écritures dans les fichiers partagés.
- [ ] Routage de modèles selon la difficulté, après une comparaison à modèle constant.
- [ ] Délégation externe seulement comme variante identifiée, avec modèle, coût et temps inclus dans les résultats.

**Validation :** chaque ajout possède une ablation et un bénéfice hors des seuls cas qui ont servi à le concevoir. Une boucle légère avec des outils fiables constitue déjà la première cible complète.

## 5. Traitement de chaque ancienne passe

| Passe actuelle | Remplacement dans le nouveau système |
| --- | --- |
| `00_project_initialization.py` | Préparation locale du workspace ; réutiliser `initialize_project()` sans appel modèle. |
| `01_explore_requirement.py` | Lecture déterministe des exigences et accès aux ressources par l’agent ; analyse visuelle à la demande. |
| `02_build_db_schema.py` | L’agent conçoit et implémente le schéma utile au parcours courant. |
| `03_infer_db_obligations.py` | Exigences et scénarios servent directement aux décisions et à l’acceptation ; aucune génération globale d’obligations imposée. |
| `04_check_db_obligations.py` | Validation locale des entrées et contrôles concrets sur la base ; retirer l’affichage de passe du chemin nominal. |
| `05_implement_db.py` | Outils d’édition et exécution de l’initialisation de base dans la session courante. |
| `06_design_backend_apis.py` | Décisions d’interface prises au besoin, avec note de contrat légère si nécessaire. |
| `07_check_backend_apis.py` | Vérification HTTP et revues ciblées ; supprimer la passe d’affichage obligatoire. |
| `08_implement_backend_tdd.py` | Implémentation et tests utiles choisis pendant le travail ; absence de génération TDD systématique par API. |
| `09_design_ui.py` | Inspection des références et choix de composants/styles pendant l’implémentation. |
| `10_implement_ui.py` | Développement de l’interface réelle avec contrôles ciblés et observation navigateur. |
| `11_design_frontend_triggers.py` | Gestion directe des interactions, appels réseau et transitions d’état dans le code. |
| `12_implement_frontend_tdd.py` | Vérification des parcours et réparations dans la même session, puis acceptation hôte. |

## 6. Organisation proposée des fichiers

Cette arborescence est une cible de migration. Les modules ne doivent être créés que lorsqu’ils ont une responsabilité réelle.

```text
main.py
profiles/
  arcbench-app/
    config.yaml
    role.md
    workflow.md
infrastructure/
  application_agent.py       # point d’entrée de notre agent et résultat applicatif
  runtime/
    messages.py              # messages, appels, résultats et usages typés
    events.py                # événements de notre moteur
    model.py                 # interface modèle et adaptateur du premier fournisseur
    tools.py                 # registre, schémas et contexte des outils
    loop.py                  # conversation -> modèle -> outils -> observations
    config.py                # configuration hôte, variables et budgets
    composer.py              # assemblage des instructions et du contexte
    state.py                 # état du run et reprise du workspace
    memory.py                # fenêtre de contexte et compaction, étape 11
    budget.py                # limites globales et comptabilité, étape 17
    reporting.py             # rapport, usage et causes d’arrêt
  tools/
    files.py                 # adaptation des lectures/éditions existantes
    requirements.py          # accès aux exigences et à la couverture
    checks.py                # contrôles exposés à l’agent
    processes.py             # commandes et serveurs, étapes 09–10
    browser.py               # actions Playwright, étape 10
  requirements/
    load.py                  # lecture/validation sans modèle
    index.py                 # accès exact et contraintes parentes
    coverage.py              # exigences et preuves de vérification
  verification/
    runner.py                # contrôles applicatifs indépendants du pipeline
    acceptance.py            # oracle des exigences, tests protégés
    evidence.py              # références aux logs, captures et résultats
  shared/
    project/                 # initialisation, dépendances, Git et templates
    ...                      # utilitaires encore nécessaires
scripts/
  package.py
  evaluate.py                # comparaisons reproductibles du nouveau moteur
tests/
  ...                        # garanties du nouveau contrat
```

Le dossier `runtime/` contient notre implémentation du moteur. Les services existants sont réutilisés lorsqu’ils restent adaptés ; les mécanismes de LingCore servent de références pour les comportements et les cas limites à tester. Aucun package, wheel ou sous-module LingCore ne fait partie de la livraison.

Les entrées originales, l’état de session et les tests protégés ont des emplacements contrôlés par l’hôte, distincts des sources modifiables. Un rapport final peut rester accessible sous `.arc/` pour compatibilité, sans réintroduire ses anciennes IR.

## 7. Contrat de fin de génération

Le succès applicatif exige des preuves adaptées aux exigences et à la livraison :

- [x] Les sources attendues existent et les exigences n’ont pas été réécrites pour correspondre au résultat.
- [x] Les dépendances et scripts de lancement sont cohérents.
- [x] La construction de production réussit.
- [x] L’initialisation et les données de démarrage demandées fonctionnent sur une base propre.
- [x] L’application démarre avec la commande publique documentée et le port prévu.
- [x] Les parcours requis sont effectivement exécutés ; tests ignorés et vérifications absentes sont visibles.
- [x] Les exigences d’identité, persistance, rejet et navigation applicables sont vérifiées.
- [x] Les preuves visuelles requises existent ; les limites d’une analyse indisponible sont explicites.
- [x] Les tests d’acceptation protégés n’ont pas été modifiés par l’agent.
- [x] Le statut final et le code de sortie reflètent ces résultats.

Une réponse `Final` du runtime, un plan marqué terminé ou un simple `/api/health` vert ne suffisent pas pour établir ce succès.

## 8. Livraisons et dépendances entre travaux

| Livraison | Étapes | Résultat concret |
| --- | --- | --- |
| A — Noyau de notre moteur | 01–04 | Baseline figée, contrats locaux, client modèle, boucle minimale testée et profil chargé par notre code. |
| B — Agent capable de développer | 05–12 | Lecture fidèle, squelette autonome, outils, navigateur et travail libre entre couches. |
| C — Résultat vérifiable | 13–18 | Acceptation découplée, couverture, finalisation et maîtrise du coût. |
| D — Moteur utilisable et livrable | 19–22 | Reprise, nouvelle CLI, suppression du pipeline et archive autonome. |
| E — Validation et optimisation | 23–24 | Comparaison contrôlée puis améliorations mesurées. |

L’acceptation peut être développée en parallèle du nouveau driver, mais la bascule nominale attend leur intégration. Commencer les petits essais fonctionnels dès la livraison B pour détecter les problèmes ; ils ne remplacent pas la validation de la livraison finale.

## 9. Risques à surveiller pendant la migration

| Risque | Réponse prévue |
| --- | --- |
| Recréer les passes dans les prompts du nouvel agent | Relire le profil et vérifier les traces : aucun artefact global ni ordre par couche obligatoire. |
| Consommer davantage avec une autonomie illimitée | Budget total, observations ciblées, détection de stagnation et réserve de finalisation. |
| Confondre un meilleur modèle avec un meilleur moteur | Comparaisons à paramètres documentés et essais à modèle constant. |
| Supprimer des IR encore nécessaires aux tests | Découpler l’acceptation avant de retirer les producteurs. |
| Autoriser les outils de fichiers mais contourner la protection par le shell | Isolation des tests et politique d’accès appliquée à tous les chemins d’exécution. |
| Perdre des exigences en n’exposant qu’une partie du document | Inventaire complet, contraintes parentes et couverture contrôlée par l’hôte. |
| Renvoyer toutes les sources pour compenser les omissions | Recherche et lectures exactes, preuves persistantes et contexte invalidé après changement. |
| Finir avec une application locale non reproductible | Validation de l’archive dans un environnement propre. |
| Introduire une incompatibilité de dépendances ou de plateforme | Installation isolée et tests de notre moteur sur les environnements retenus. |
| Sous-estimer le travail d’un moteur propre | Livrer d’abord une boucle testée ; développer streaming, mémoire, persistance et isolation avec des tests de fautes ciblés. |
| Augmenter la mémoire, les skills ou les revues sans bénéfice | Ajouts après baseline, ablations et coût de tous les appels secondaires comptabilisé. |

## 10. Références dans les sources examinées

### Projet actuel

- [CLI](main.py) et [orchestrateur des 13 passes](infrastructure/compiler.py).
- [Boucle d’édition](infrastructure/shared/agent/loop.py), [propositions JSON](infrastructure/shared/agent/proposals.py), [protocole des outils](infrastructure/shared/agent/tools/protocol.py).
- [Client texte](infrastructure/shared/models/text.py), [contexte](infrastructure/shared/agent/context.py), [découverte](infrastructure/shared/agent/discovery.py).
- [Initialisation](infrastructure/shared/project/initialize.py), [installation](infrastructure/shared/project/dependencies.py), [templates](infrastructure/shared/project/templates/).
- [Acceptation actuelle](infrastructure/stages/frontend/triggers/acceptance.py) et [packaging Arcbench](scripts/package.py).
- [Catalogue historique d’expériences](IDEES_AMELIORATION_AGENT.md).

### LingCore 0.6.1, archive locale examinée

Ces liens pointent vers la copie extraite pour l’analyse. Ils ne sont pas des dépendances à conserver dans l’application livrée.

- [API Agent et assemblage](../.comparison/LingCore-main/lingcore/agent.py).
- [Construction depuis un profil](../.comparison/LingCore-main/lingcore/_agent/profile.py).
- [Driver headless et budgets](../.comparison/LingCore-main/lingcore/execution.py).
- [Contrat des outils](../.comparison/LingCore-main/lingcore/tools/__init__.py).
- [Composition des instructions](../.comparison/LingCore-main/lingcore/composer.py).
- [Mémoire](../.comparison/LingCore-main/lingcore/memory.py), [sessions](../.comparison/LingCore-main/lingcore/sessions.py), [événements](../.comparison/LingCore-main/lingcore/events.py).
- [Workflow frontend](../.comparison/LingCore-main/profiles/frontend/workflow.md) et [profil coding](../.comparison/LingCore-main/profiles/coding/config.yaml).
- [Manifeste et dépendances](../.comparison/LingCore-main/pyproject.toml).

## 11. Définition de migration terminée

- [x] Le lancement normal utilise une session d’agent pour l’application.
- [x] La boucle, les sessions, le registre d’outils et les adaptateurs fournisseur appartiennent au projet ; aucun import ou package LingCore n’est nécessaire à leur exécution.
- [x] Aucun script `00` à `12` n’est importé ou requis pour générer et livrer.
- [x] Aucune IR de schéma, obligations, API, UI ou triggers n’est exigée comme passage préalable.
- [x] L’agent choisit ses actions et peut corriger plusieurs couches dans une même tâche.
- [x] Le résultat reste vérifié par l’hôte à partir des exigences originales.
- [x] L’installation, le packaging, la reprise et l’arrêt sont reproductibles.
- [ ] Les résultats Arcbench, tokens et durées du nouveau moteur sont publiés avec leur configuration exacte, y compris les échecs.

La migration architecturale et son bénéfice mesuré sont deux critères distincts : le premier exige la disparition effective du pipeline fixe ; le second exige les comparaisons de l’étape 23.

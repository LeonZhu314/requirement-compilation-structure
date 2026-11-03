# Améliorer le Requirement Compiler : 120 expériences à tester

Date : 3 novembre 2026.

Ce document propose un catalogue d'expérimentations à partir du code du projet. Chaque piste est une hypothèse, accompagnée d'un essai concret et d'une mesure. Les gains restent à établir : la prise de connaissance initiale était une revue du code, sans exécution complète du pipeline ni de sa suite de tests.

L'objectif est d'augmenter la proportion d'applications qui satisfont réellement les exigences, puis de réduire le coût, la durée et les interventions nécessaires pour les produire.

## Sommaire

- [Point de départ et principes à préserver](#point-de-départ-et-principes-à-préserver)
- [Les premiers essais à lancer](#les-premiers-essais-à-lancer)
- [Protocole commun de comparaison](#protocole-commun-de-comparaison)
- [Catalogue des expériences](#catalogue-des-expériences)
- [Ordre de mise en œuvre proposé](#ordre-de-mise-en-œuvre-proposé)
- [Fiche à remplir pour chaque expérience](#fiche-à-remplir-pour-chaque-expérience)
- [Pièges à éviter](#pièges-à-éviter)
- [Références externes](#références-externes)

## Point de départ et principes à préserver

### Ce qui existe déjà

| Élément | État observé dans le code | Points d'entrée |
| --- | --- | --- |
| Orchestration | 13 passes successives ; les échecs sont conservés dans les rapports et les passes suivantes sont tentées. | [main.py](main.py), [compiler.py](infrastructure/compiler.py) |
| Exigences | Arbre YAML, exigences feuilles, scénarios Given/When/Then et références visuelles. | [tree.py](infrastructure/stages/requirements/tree.py), [exemple](input/requirements.yaml) |
| Représentations intermédiaires | Schéma, obligations, API, UI et triggers publiés sous le répertoire de sortie .arc. | [stages](infrastructure/stages/) |
| Contraintes de données | Les API et triggers doivent couvrir les lectures requises et respecter l'ensemble des écritures possibles déclaré pour l'exigence. Les références ne signifient pas réexécuter leurs effets. | [primitives.py](infrastructure/stages/backend/primitives.py), [records.py](infrastructure/stages/database/obligations/records.py), [triggers/design.py](infrastructure/stages/frontend/triggers/design.py) |
| Recherche | BM25 pour les schémas/API/pages ; découverte lexicale, pagination et lectures exactes à la demande. | [rag](infrastructure/shared/rag/), [discovery.py](infrastructure/shared/agent/discovery.py) |
| Mémoire | Conventions partagées entre exigences ; preuves consultées conservées pendant une tâche. | [conventions.py](infrastructure/shared/agent/conventions.py), [loop.py](infrastructure/shared/agent/loop.py) |
| Outils | Lecture par lignes et édition locale ; contrôle des chemins, droits par tâche et restauration d'un lot d'éditions si son application échoue. | [tools](infrastructure/shared/agent/tools/) |
| Réparation | Retours d'erreur, nouvelles propositions, checks réels, archivage et restauration du point de départ d'une tâche épuisée. | [proposals.py](infrastructure/shared/agent/proposals.py), [recovery.py](infrastructure/shared/agent/recovery.py) |
| Validation | Tests HTTP sur serveur réel, tests UI, parcours navigateur et acceptation issue des exigences d'origine. | [backend/testing.py](infrastructure/stages/backend/testing.py), [ui/testing.py](infrastructure/stages/frontend/ui/testing.py), [acceptance.py](infrastructure/stages/frontend/triggers/acceptance.py) |
| Exécution | Application React/Vite, Express et SQLite ; initialisation, données prérequises et environnements de test isolés. | [templates](infrastructure/shared/project/templates/), [database](infrastructure/stages/database/) |
| Modèles et traces | Clients texte/vision configurables, statistiques d'usage, logs détaillés facultatifs et checkpoints Git de la sortie. | [models](infrastructure/shared/models/), [presentation](infrastructure/utils/presentation/), [git.py](infrastructure/shared/project/git.py) |

### Limites à examiner expérimentalement

Ces constats portent sur les mécanismes présents, et ne constituent pas des résultats de benchmark :

- Le nombre de tours d'édition ou de propositions ne borne pas, à lui seul, tous les appels : les recherches et lectures utiles peuvent provoquer plusieurs appels à l'intérieur d'un tour.
- Des erreurs structurelles sont actuellement détectées lorsque le code consomme une réponse, plutôt que systématiquement avant sa publication.
- Les préconditions et postconditions sont décrites dans les contrats, mais ne font pas l'objet d'une preuve formelle générale. La couverture déclarée des champs ne prouve pas l'exécution correcte du code.
- Certaines passes de revue affichent surtout des artefacts. Leur intitulé ne doit pas être interprété comme une validation sémantique supplémentaire.
- L'acceptation indépendante bénéficie d'une séparation des droits, mais utilise encore des interfaces générées et le modèle fourni au pipeline. Elle est indépendante de certaines sources d'implémentation, pas de toute décision précédente.
- Le parcours fourni couvre principalement l'authentification. Il ne permet pas, seul, d'estimer la généralisation à d'autres applications.
- Le point d'entrée principal peut terminer avec un code de sortie zéro après certaines défaillances. La mesure du succès doit donc lire les résultats réels, pas seulement le code du processus.

### Principes à conserver pendant les essais

1. Une exigence reste traçable jusqu'aux tests qui la vérifient.
2. Les conventions et contrats partagés restent canoniques ; une tâche locale ne peut effacer les comportements précédents.
3. Les données de Given ne deviennent pas artificiellement des effets du When.
4. Les tests d'acceptation gardent des attentes issues des exigences d'origine.
5. Le périmètre lecture/écriture des outils est appliqué par le programme hôte.
6. Une sortie partielle, une étape ignorée ou une validation absente ne deviennent jamais un succès complet.
7. Un changement de modèle, de contexte ou de prompt est évalué comme une variante à part entière.

## Les premiers essais à lancer

Priorités : **P0** = fiabiliser le résultat ou sa mesure ; **P1** = premier cycle d'optimisation ; **P2** = extension après mesure ; **P3** = piste de recherche.

Effort relatif : **F** = faible, **M** = moyen, **E** = élevé. Ces indications servent à comparer les pistes ; elles ne constituent pas un chiffrage.

| Ordre | Expérience | Pourquoi commencer ici | Critère principal |
| --- | --- | --- | --- |
| 1 | R01 — Comptabilité complète | Sans mesure fiable, les optimisations de coût ne sont pas comparables. | Appels, tokens et durée attribués à chaque tâche, y compris échecs et retries. |
| 2 | L01 — Suite externe figée | Réduit le risque de mesurer uniquement les tests produits par l'agent. | Réussite complète sur des attentes indépendantes et stables. |
| 3 | A01 — Statuts et sortie stricts | Évite de confondre fin du processus et application validée. | Aucun succès affiché pour une validation requise manquante ou échouée. |
| 4 | J01 — Budget de tous les appels | Les tours actuels ne représentent pas le budget réel. | Arrêt explicite avant dépassement des limites configurées. |
| 5 | B01 — Entrées validées | Évite de lancer des appels coûteux sur un document incohérent. | Erreurs d'identifiants, de types et de références détectées sans modèle. |
| 6 | C01/C02 — IR structurée et liée | Détecte les références cassées avant les passes coûteuses. | Défauts structurels détectés, sans rejets métier injustifiés. |
| 7 | J02 — Détection d'absence de progrès | Une boucle peut varier sa formulation sans résoudre la panne. | Moins d'appels gaspillés, réussite finale préservée. |
| 8 | F02 — Interfaces puis lectures ciblées | Évalue une réduction du contexte sans sacrifier les preuves. | Moins de tokens pour une réussite externe comparable. |
| 9 | E04 — Récupération par dépendances | Les dépendances réelles complètent les correspondances lexicales. | Meilleur rappel des références nécessaires à coût contenu. |
| 10 | K02 — Raisonnement adaptatif | Le niveau faible configuré partout est une baseline à comparer. | Meilleur compromis réussite/coût sur les tâches difficiles. |
| 11 | L02 — Mutation testing | Mesure si les tests détectent réellement un code faux. | Davantage de défauts métier injectés détectés. |
| 12 | A03 — Reprise contrôlée | Évite de refaire tout le travail après une interruption. | Résultat équivalent après reprise, avec moins de travail rejoué. |

## Protocole commun de comparaison

### Constituer les jeux d'essai

- Conserver le module d'authentification actuel comme cas de référence.
- Ajouter des cas avec CRUD, listes et filtres, relations multiples, rôles, transactions, formulaires d'édition, erreurs métier et routes dynamiques.
- Ajouter des variantes longues, multilingues, ambiguës, contradictoires et sans image. Les cas invalides doivent attendre un diagnostic explicite, pas une application inventée.
- Ajouter de petites modifications d'un projet déjà généré : changement de contrat, nouvelle exigence, correction d'une règle, ajout d'un champ.
- Distinguer développement, validation des choix et test final réservé. Une correction inspirée d'un cas de test final transforme ce cas en donnée de développement.
- Utiliser un échantillon pilote pour filtrer les idées ; élargir ensuite aux catégories de tâches concernées. La taille du pilote ne suffit pas à prouver un gain général.

### Comparer à conditions documentées

Pour chaque variante, conserver les versions du compilateur, des prompts, des modèles, des dépendances, des entrées, des tests et de l'environnement. Utiliser une sortie et une base distinctes par exécution.

Comparer les variantes sur les mêmes tâches, avec plusieurs exécutions indépendantes quand la génération est variable. Une graine, si le fournisseur l'accepte, n'est pas une garantie de déterminisme. Alterner l'ordre des variantes pour limiter l'effet des conditions du service. Séparer les résultats à cache froid et à cache chaud.

Ne changer qu'un facteur à la fois pour comprendre sa contribution. Les combinaisons prometteuses viennent après les essais isolés. Fixer les budgets avant le lancement et conserver les échecs, interruptions et dépassements dans les résultats.

### Mesures communes

| Mesure | Définition et précautions |
| --- | --- |
| Réussite complète | Part des exécutions qui satisfont toutes les validations requises et la suite externe, sans réparation humaine. Une vérification manquante vaut « non vérifié ». |
| Satisfaction partielle | Exigences et branches satisfaites rapportées au nombre attendu, avec les omissions visibles. À publier séparément de la réussite complète. |
| Faux succès observés | Exécutions annoncées réussies qui échouent à une vérification externe. Publier aussi le nombre de succès soumis à cette vérification. |
| Régression | Comportements précédemment validés qui échouent après une nouvelle exigence ou un correctif. |
| Coût par exécution | Coût facturé si disponible, sinon usage fournisseur conservé avec la mention « coût indisponible ». Ne pas inventer le tarif d'un endpoint compatible. |
| Coût par réussite | Dépense totale de la variante, échecs compris, divisée par ses réussites complètes. Indéfini si aucune réussite. |
| Durée | Temps jusqu'à la réussite ou à l'arrêt ; médiane et dispersion. Les durées extrêmes nécessitent suffisamment d'observations pour être interprétées. |
| Réparation | Taux de correction au premier essai, appels/tours nécessaires, oscillations, abandons et interventions humaines. |
| Contexte | Tokens réellement rapportés, taille des sources envoyées, recherches, lectures répétées et preuves manquantes. |
| Qualité des tests | Défauts injectés détectés, branches métier vérifiées, instabilité et capacité à distinguer deux identités ou objets. |
| Qualité visuelle | Écart sur des critères fixés à l'avance ; publier séparément la conformité fonctionnelle. |

Avant l'essai, définir le gain minimal utile et les régressions inacceptables. Un objectif tel que « réduire le coût d'au moins 10 % sans perte significative de réussite » est un exemple à calibrer, pas un résultat acquis. Sur un petit échantillon, publier les résultats par tâche et l'incertitude plutôt qu'une conclusion statistique forte.

## Catalogue des expériences

Chaque ligne décrit une expérience indépendante. Les points d'intégration indiquent où commencer, sans imposer de réécriture générale.

### A — Orchestration et compilation incrémentale

Points d'intégration : [compiler.py](infrastructure/compiler.py), [main.py](main.py), [recovery.py](infrastructure/shared/agent/recovery.py), [files.py](infrastructure/utils/files.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| A01 | P0 / F | Définir une table de statuts autorisés et une règle finale explicite ; tester échec, interruption, tâche omise et statut inconnu. Ajouter un mode CLI strict avec sortie non nulle si une validation requise échoue. | Concordance entre résultat annoncé, rapport et validations ; zéro faux succès sur les cas injectés. |
| A02 | P1 / E | Décrire les dépendances des passes dans un graphe. Comparer la poursuite actuelle à une politique qui tente les branches indépendantes et marque les autres « prérequis indisponible ». | Réussites utiles préservées et appels évitables après panne amont. |
| A03 | P1 / E | Ajouter une reprise après interruption, fondée sur des empreintes vérifiées. Interrompre après plusieurs frontières de passes puis reprendre. | Équivalence avec une exécution fraîche, absence de mélange d'artefacts et travail évité. |
| A04 | P2 / E | Invalider seulement les artefacts dépendant d'une exigence, d'un prompt, d'un modèle ou d'un contrat modifié. Comparer avec une recompilation complète. | Même résultat externe avec moins de passes et aucune réutilisation périmée. |
| A05 | P2 / M | Calculer des différences sémantiques d'IR : ajout de champ, changement d'écriture, signature incompatible ou contrôle supprimé. Les montrer avant publication et les utiliser pour cibler les vérifications. | Changements incompatibles détectés et régressions évitées. |
| A06 | P1 / M | Publier un ensemble d'artefacts avec manifeste et identifiant de génération, après validation de cohérence. Simuler une interruption entre deux écritures. | Aucune lecture d'un ensemble partiellement publié comme état courant valide. |

La reprise doit vérifier les fichiers actuels et leurs dépendances ; un ancien rapport GREEN ne constitue pas une nouvelle preuve.

### B — Compréhension et représentation des exigences

Points d'intégration : [01_explore_requirement.py](01_explore_requirement.py), [tree.py](infrastructure/stages/requirements/tree.py), [frontend/context.py](infrastructure/stages/frontend/context.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| B01 | P0 / M | Valider explicitement les types YAML, l'unicité globale des identifiants, les listes, les chemins et les références. Introduire doublons et collections mal formées. | Erreurs localisées avant tout appel modèle, sans écrasement silencieux d'un nœud. |
| B02 | P1 / M | Ajouter une analyse d'ambiguïtés et contradictions, avec extraits justificatifs. Comparer diagnostic seul, clarification humaine et hypothèse explicite pour les cas réellement indécidables. | Moins de décisions métier inventées et coût des clarifications utiles. |
| B03 | P1 / E | Relier chaque élément d'IR à une exigence et à son passage justificatif. Évaluer si l'agent peut expliquer un champ, un endpoint ou un comportement sans preuve. | Taux d'éléments sans justification et précision des liens de provenance. |
| B04 | P1 / M | Représenter les références entre exigences comme relations typées : navigation, prérequis, résultat réutilisé, état existant. Comparer avec les références textuelles actuelles. | Moins de mutations héritées à tort et de dépendances métier oubliées. |
| B05 | P1 / M | Définir le traitement des règles métier placées sur un parent. Comparer rejet explicite de ce format, contexte hérité borné et normalisation vers les feuilles. | Règles parentales préservées sans duplication de travail ou d'effets. |
| B06 | P2 / M | Construire une matrice d'exigences observables : succès, rejet, état initial, persistance, isolation, limites de périmètre. Signaler les cases non spécifiées sans les remplir arbitrairement. | Omissions repérées et nouveaux scénarios réellement justifiés. |

La normalisation doit préserver les formulations imposées, les comparaisons exactes, la langue et les distinctions entre données de préparation et actions testées.

### C — Représentations intermédiaires et contrats

Points d'intégration : [database/schema.py](infrastructure/stages/database/schema.py), [backend/primitives.py](infrastructure/stages/backend/primitives.py), [ui/design.py](infrastructure/stages/frontend/ui/design.py), [triggers/design.py](infrastructure/stages/frontend/triggers/design.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| C01 | P0 / M | Définir des schémas versionnés pour les réponses et artefacts : propriétés requises, types, unions et extensions autorisées. Comparer validation préalable et erreurs de consommation actuelles. | Propositions invalides publiées, erreurs réparables et taux de rejet injustifié. |
| C02 | P0 / M | Vérifier les liens de l'IR : parents UI existants, cycles interdits, racines, variables, API et triggers résolus, associations d'étapes complètes. Injecter un défaut de chaque classe. | Détection avant implémentation, précision des messages et absence de faux blocages. |
| C03 | P2 / E | Rendre exécutables certains contrats simples : statut, présence de champ, unicité, non-écriture sur rejet. Garder la prose pour ce qui ne se formalise pas proprement. | Contradictions détectées et comportements vérifiés en plus des tests générés. |
| C04 | P2 / E | Enrichir les obligations avec portée, condition et distinction données lues/données exposées. Tester une branche de rejet, une lecture de hachage et un affichage public. | Moins de confusion entre capacité d'accès, effet conditionnel et fuite de donnée. |
| C05 | P2 / E | Comparer les effets déclarés aux observations SQL/HTTP pendant des scénarios contrôlés. Rapporter les écarts sans prétendre que la trace couvre tous les chemins. | Écritures interdites détectées, couverture dynamique connue et faux positifs. |
| C06 | P1 / E | Versionner les interfaces canoniques et analyser l'impact d'un changement sur leurs consommateurs antérieurs. Tester ajout compatible, renommage et changement de transport de session. | Consommateurs affectés identifiés et comportements antérieurs préservés. |

Commencer par la structure et les références. Un schéma JSON bien formé ne prouve pas la justesse métier. JSON Schema distingue notamment les propriétés déclarées, les propriétés requises et les propriétés supplémentaires autorisées : [documentation officielle](https://json-schema.org/understanding-json-schema/reference/object).

### D — Planification et décomposition des tâches

Points d'intégration : [compiler.py](infrastructure/compiler.py), [tasks.py](infrastructure/shared/agent/tasks.py), [loop.py](infrastructure/shared/agent/loop.py), scripts de passes.

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| D01 | P1 / F | Demander un plan bref des fichiers et invariants avant une réparation complexe, puis confronter le patch à ce plan. Comparer avec l'édition directe. | Réussite du premier patch, tokens supplémentaires et modifications hors sujet. |
| D02 | P2 / M | Comparer l'ordre documentaire à un ordre guidé par les dépendances pour concevoir schémas et API. Utiliser plusieurs permutations d'une même spécification. | Stabilité des noms, duplications et réussite finale selon l'ordre. |
| D03 | P2 / E | Adapter la granularité : tâche unique pour cas simple, sous-tâches coordonnées pour une exigence volumineuse. Conserver un propriétaire du contrat et une validation globale. | Coût de coordination, omissions entre sous-tâches et régressions. |
| D04 | P1 / E | Autoriser un retour amont typé lorsque le contrat est irréalisable : demande de correction de schéma ou API avec preuve et liste d'impacts. Borner les cycles. | Pannes résolues à leur source, oscillations entre passes et coût total. |
| D05 | P2 / M | Distinguer les dépendances indispensables au scénario des comportements de pages simplement atteignables. Tester un parcours traversant des pages partagées. | Moins d'implémentations hors périmètre, avec prérequis du parcours satisfaits. |
| D06 | P3 / E | Produire un petit nombre de plans ou patches candidats sur les tâches difficiles, dans des sorties isolées, puis sélectionner par les mêmes checks. | Gain de réussite à budget total égal, et fréquence de sélection du meilleur candidat. |

Une orchestration plus élaborée doit justifier son coût. Les architectures workflow, routage et évaluation itérative constituent des variantes possibles, pas une garantie de supériorité : [Building effective agents](https://www.anthropic.com/research/building-effective-agents).

### E — RAG et découverte des dépendances

Points d'intégration : [bm25.py](infrastructure/shared/rag/bm25.py), [schema.py](infrastructure/shared/rag/schema.py), [apis.py](infrastructure/shared/rag/apis.py), [pages.py](infrastructure/shared/rag/pages.py), [discovery.py](infrastructure/shared/agent/discovery.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| E01 | P1 / F | Améliorer la recherche lexicale : synonymes contrôlés, identifiants, variantes multilingues et pondération des champs. Construire des requêtes annotées. | Rappel et précision des références nécessaires, puis effet sur la réussite. |
| E02 | P2 / M | Comparer BM25 seul à une recherche sémantique et à leur combinaison. Garder les noms canoniques et la possibilité d'une lecture exacte. | Réussite externe, tokens ajoutés, latence et coût d'indexation. |
| E03 | P2 / M | Réordonner un petit ensemble de candidats avec un second score ou modèle. Tester seulement si le candidat correct apparaît déjà dans cet ensemble. | Précision en tête de classement et gain net après coût du réordonnancement. |
| E04 | P1 / M | Ajouter les voisins utiles du graphe : clés étrangères, consommateurs d'API, parents UI, imports et propriétaires d'un test. Borner l'expansion par type de relation. | Dépendances retrouvées et croissance du contexte par tâche. |
| E05 | P1 / M | Après une recherche infructueuse, reformuler une seule requête avec les concepts manquants, puis lire des identifiants précis. Comparer à la répétition libre actuelle. | Nouveaux faits utiles par appel et absence de création de doublon après faux négatif. |
| E06 | P2 / M | Ajuster le nombre de résultats à l'incertitude et à leur diversité ; comparer plusieurs budgets fixes à cette politique. | Réussite par token de contexte et taux de références indispensables manquantes. |

Évaluer séparément la qualité du classement et la réussite de génération. Un meilleur score de recherche ne garantit pas une meilleure application.

### F — Gestion du contexte

Points d'intégration : [context.py](infrastructure/shared/agent/context.py), [discovery.py](infrastructure/shared/agent/discovery.py), [loop.py](infrastructure/shared/agent/loop.py), [feedback.py](infrastructure/shared/agent/feedback.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| F01 | P1 / M | Répartir un budget de contexte entre tâche, contrats, sources, preuves et erreurs. Comparer plusieurs répartitions, sans couper silencieusement un contrat nécessaire. | Tokens, preuves manquantes et réussite externe à budget constant. |
| F02 | P1 / M | Fournir d'abord signatures, imports, symboles et extraits pertinents ; ouvrir le corps complet sur demande. Comparer aux fichiers complets actuellement épinglés. | Réduction des entrées sans hausse des erreurs liées au contexte. |
| F03 | P1 / M | Associer chaque preuve à une empreinte de contenu et à sa provenance. Étendre la détection des extraits périmés aux contrats et décisions partagées. | Aucune décision fondée sur une version obsolète lors des mutations injectées. |
| F04 | P2 / M | Résumer les essais précédents en faits, hypothèses rejetées et vérifications encore nécessaires. Conserver les preuves exactes référencées, accessibles sur demande. | Moins de répétitions, pertes d'informations et tokens par réparation. |
| F05 | P1 / M | Localiser les erreurs avec fichiers, symboles, pile et dépendances immédiates ; comparer cette sélection aux seuls noms de fichiers trouvés dans les logs. | Précision des sources fournies et nombre d'itérations de diagnostic. |
| F06 | P2 / M | Mettre en cache les index et résolutions de dépendances par empreinte. Les invalider dès qu'une source ou un artefact change. | Temps de préparation et mêmes résultats qu'un index reconstruit. |

Éviter un plafond uniforme qui supprimerait les éléments décisifs. Mesurer le volume utile, les doublons et les omissions séparément.

### G — Mémoire et apprentissage entre tâches

Points d'intégration : [conventions.py](infrastructure/shared/agent/conventions.py), [loop.py](infrastructure/shared/agent/loop.py), [recovery.py](infrastructure/shared/agent/recovery.py), [git.py](infrastructure/shared/project/git.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| G01 | P2 / M | Enregistrer une leçon de réparation uniquement après validation : symptôme, cause, patch minimal, contexte d'application et preuves. Comparer mémoire désactivée/activée. | Réussite et coût sur nouvelles tâches similaires, avec erreurs de transfert comptées. |
| G02 | P2 / M | Conserver les impasses validées : correctif essayé, cause de rejet et conditions où il ne faut pas le reproduire. Prévoir expiration et invalidation. | Répétitions évitées sans exclusion abusive d'une solution adaptée à un autre contexte. |
| G03 | P1 / M | Faire évoluer les conventions en décisions versionnées avec source, propriétaire et consommateurs. Tester une correction coordonnée de transport de session. | Conflits explicites et consommateurs migrés sans perte de comportement. |
| G04 | P2 / M | Séparer mémoire du projet et mémoire réutilisable. Filtrer par pile, version, type de panne et empreintes ; empêcher la circulation de valeurs privées entre projets. | Pertinence des souvenirs récupérés et absence de contamination entre cas. |
| G05 | P2 / M | Transformer des trajectoires réussies en quelques exemples courts de diagnostic et d'édition. Comparer exemples proches, aléatoires et absence d'exemple. | Taux de correction, coût et copie indue de noms ou valeurs d'exemple. |
| G06 | P3 / E | Réviser les prompts ou règles de sélection hors ligne à partir des erreurs récurrentes. Promouvoir une révision seulement après validation réservée. | Gain reproductible hors des tâches ayant inspiré la révision. |

La mémoire doit distinguer fait confirmé, décision métier et hypothèse. Une correction locale ne devient pas automatiquement une règle universelle.

### H — Skills et recettes de travail

Points d'intégration : assemblage des prompts dans [proposals.py](infrastructure/shared/agent/proposals.py) et [loop.py](infrastructure/shared/agent/loop.py). Le projet ne possède pas actuellement de chargeur de skills.

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| H01 | P2 / M | Ajouter un chargeur minimal de guides versionnés et ne sélectionner que ceux liés à la tâche : SQL, React, contrat HTTP ou réparation de test. | Réussite, erreurs ciblées et tokens ajoutés par sélection. |
| H02 | P2 / F | Déclarer les prérequis d'une recette : pile, versions compatibles, preuves nécessaires et contraintes d'usage. Tester une recette incompatible volontairement. | Recettes inapplicables écartées et diagnostics compréhensibles. |
| H03 | P2 / M | Associer une recette à une demande de capacités, tout en laissant l'hôte calculer les droits effectifs. Tester qu'un guide ne peut élargir ses propres permissions. | Rejet des accès hors périmètre et tâches légitimes réalisables. |
| H04 | P2 / M | Créer des recettes courtes pour erreurs concrètes : import ESM, clé étrangère, formulaire soumis deux fois, état périmé. Comparer avec le prompt générique. | Baisse des erreurs récurrentes sur un jeu distinct de celui de rédaction. |
| H05 | P2 / M | Donner à chaque recette des cas positifs, négatifs et adverses exécutables. Refuser une mise à jour qui corrige un cas en cassant les autres. | Régressions détectées avant diffusion d'une recette. |
| H06 | P2 / F | Comparer injection systématique de tous les guides, sélection automatique et sélection déterministe par type de tâche. | Réussite à budget égal et proportion de guidance sans rapport avec le problème. |

Commencer par quelques recettes issues de pannes constatées. Ajouter un système de skills volumineux avant d'avoir ces données pourrait augmenter le contexte sans bénéfice.

### I — Outils et interaction avec le projet généré

Points d'intégration : [tools/schemas.py](infrastructure/shared/agent/tools/schemas.py), [tools/files.py](infrastructure/shared/agent/tools/files.py), [tools/__init__.py](infrastructure/shared/agent/tools/__init__.py), [loop.py](infrastructure/shared/agent/loop.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| I01 | P1 / M | Ajouter une recherche textuelle bornée retournant chemin, lignes et contexte, sur les seules sources autorisées. Comparer aux recherches de fichiers et lectures successives. | Fichiers pertinents trouvés, lectures nécessaires et volume retourné. |
| I02 | P2 / F | Ajouter une arborescence limitée à un sous-répertoire autorisé, avec pagination et exclusions. Tester son utilité quand l'organisation réelle diffère du template. | Erreurs de chemins et appels consacrés à découvrir la structure. |
| I03 | P2 / E | Ajouter lecture et édition par symbole AST pour TypeScript/Python, avec aperçu du diff et refus des correspondances ambiguës. Comparer à la substitution exacte. | Échecs de patch, modifications involontaires et coût de localisation. |
| I04 | P2 / E | Exposer signatures, références et diagnostics du compilateur TypeScript via une interface de lecture. Tester les migrations d'une fonction partagée. | Appels manqués après renommage et durée de réparation des erreurs de type. |
| I05 | P2 / M | Permettre de demander des checks prédéfinis et typés : compilation, suite précise, build. L'hôte conserve les commandes, ressources, limites et validations obligatoires finales. | Boucles inutiles évitées et absence de contournement du gate. |
| I06 | P2 / M | Comparer le protocole JSON texte actuel à un adaptateur d'appels d'outils natifs, lorsque le fournisseur le supporte. Garder les mêmes exécuteurs et droits. | Réponses mal formées, portabilité, latence et coût total. |

Toute nouvelle capacité doit conserver les protections de chemins, les fichiers réservés, l'atomicité logique des lots et la séparation entre lecture et mutation.

### J — Boucles de réparation et stratégie d'arrêt

Points d'intégration : [loop.py](infrastructure/shared/agent/loop.py), [proposals.py](infrastructure/shared/agent/proposals.py), [discovery.py](infrastructure/shared/agent/discovery.py), [recovery.py](infrastructure/shared/agent/recovery.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| J01 | P0 / M | Compter tous les appels, recherches, lectures, tokens rapportés et durées, y compris dans les boucles internes. Ajouter plafonds par tâche et exécution, réserves de sortie et arrêt typé. | Limites respectées ; dépassement explicite plutôt qu'épuisement invisible. |
| J02 | P1 / M | Détecter les cycles de diagnostic, de patch et de panne, au-delà des recherches identiques déjà reconnues. Exiger une nouvelle preuve ou une autre stratégie après stagnation. | Appels sans progrès et tâches abandonnées malgré une solution accessible. |
| J03 | P1 / M | Produire un diagnostic court lié aux preuves : cause probable, fichier responsable, correction attendue, vérification discriminante. Mesurer la justesse plutôt que la longueur. | Attribution correcte de la cause et réussite du patch suivant. |
| J04 | P1 / M | Traiter automatiquement quelques erreurs certaines : BOM, chemin adapté, import dont la cible est prouvée, format de réponse. Comparer au traitement intégral par modèle. | Appels évités et absence de correction métier silencieuse. |
| J05 | P1 / M | Étendre la séparation « revue du test / réparation du code » aux suites générées ordinaires pour les cas douteux. Autoriser un correctif de test seulement avec preuve de l'exigence. | Tests affaiblis, défauts masqués et réparations de tests réellement justifiées. |
| J06 | P2 / M | Comparer accumulation des patches rejetés, retour au dernier état validé et branche isolée par hypothèse. Tester notamment les réparations qui oscillent. | Régressions introduites, progrès conservé et coût de reprise. |

Un échec d'environnement, une assertion métier et une erreur de protocole doivent garder des statuts distincts. Aucun ne prouve à lui seul que l'application est correcte.

### K — Choix des modèles et budget de génération

Points d'intégration : [text.py](infrastructure/shared/models/text.py), [vision.py](infrastructure/shared/models/vision.py), [model_io.py](infrastructure/utils/presentation/model_io.py), [.env.example](.env.example).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| K01 | P1 / M | Router les tâches vers plusieurs profils : conception, code, diagnostic, vision et revue. Comparer au modèle unique, avec la même enveloppe totale. | Réussite complète et coût par réussite, y compris le coût du routage. |
| K02 | P1 / M | Comparer le raisonnement faible actuel à une montée de niveau après panne difficile ou stagnation. Tester plusieurs déclencheurs observables. | Gain sur les cas difficiles, coût supplémentaire et escalades inutiles. |
| K03 | P1 / F | Adapter le plafond de sortie au type de réponse attendu : petit patch, contrat ou nouvelle page. Mesurer les troncatures et préserver assez de budget pour le JSON final. | Sorties complètes, coût et latence ; aucun gain apparent obtenu par troncature. |
| K04 | P1 / M | Décrire les capacités réellement acceptées par chaque endpoint : images, format JSON, outils, paramètres de raisonnement et budget. Tester la configuration avant la compilation. | Rejets de paramètres et bascules de fournisseur non détectées dans les résultats. |
| K05 | P2 / F | Comparer les réglages de variabilité supportés par le fournisseur. Répéter les tâches simples et difficiles sans supposer qu'un réglage bas garantit la justesse. | Dispersion des résultats, diversité utile et réussite à budget égal. |
| K06 | P1 / M | Harmoniser délais, backoff et annulation entre couches ; distinguer erreur transitoire, quota, refus et sortie invalide. Injecter des pannes de transport. | Requêtes supplémentaires, temps d'arrêt et absence de retry inutile ou infini. |

Ne pas attribuer un gain au prompt si le fournisseur, la version du modèle, le cache ou le budget ont changé. Aucun classement de modèles ni tarif n'est présumé dans ce document.

### L — Qualité des tests et indépendance de l'oracle

Points d'intégration : [input/tests](input/tests/), [08_implement_backend_tdd.py](08_implement_backend_tdd.py), [acceptance.py](infrastructure/stages/frontend/triggers/acceptance.py), [tests](tests/).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| L01 | P0 / M | Exécuter une suite externe figée, inaccessible en écriture aux réparateurs. Partir des tests fournis dans input/tests avec un runner séparé et une préparation de données explicite, sans supposer qu'ils sont déjà raccordés au pipeline. | Réussite indépendante et écart avec les résultats annoncés par les suites générées. |
| L02 | P1 / M | Injecter des mutants métier : toujours le premier utilisateur, mot de passe ignoré, rejet avec écriture, session non invalidée, filtre supprimé. Évaluer les suites sur copies isolées. | Proportion de mutants non équivalents détectés ; distinguer échec de compilation et détection du défaut. |
| L03 | P2 / E | Ajouter des tests de propriétés et de séquences : annuler préserve les données, une lecture ne modifie rien, créer puis relire retrouve la bonne identité. Réduire automatiquement les séquences qui échouent. | Défauts nouveaux détectés et taille des contre-exemples reproductibles. |
| L04 | P1 / M | Standardiser des scénarios à deux utilisateurs et deux objets, avec rejet, rechargement et persistance selon les exigences. Comparer aux scénarios à une seule identité. | Défauts d'isolation et réponses associées au mauvais objet détectés. |
| L05 | P2 / M | Comparer le même modèle à un modèle ou prompt de revue distinct pour l'acceptation. Masquer implémentation et tests de processus au réviseur. | Faux succès détectés en plus, faux rejets et coût additionnel. |
| L06 | P1 / M | Maintenir un jeu de développement consultable et une suite finale réservée, figée avant réparation. Une suite utilisée pour guider un patch devient une suite de développement. | Gain conservé sur les cas jamais utilisés comme feedback. |

Le mutation testing évalue la capacité des tests à réagir à une modification de code ; les mutants survivants doivent être interprétés, notamment s'ils sont équivalents : [Stryker](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/). Les machines à états permettent de générer des actions et leurs paramètres : [Hypothesis](https://hypothesis.readthedocs.io/en/latest/stateful.html).

### M — Base de données, schéma et données prérequises

Points d'intégration : [database/schema.py](infrastructure/stages/database/schema.py), [database/implementation.py](infrastructure/stages/database/implementation.py), [database/testing.py](infrastructure/stages/database/testing.py), [templates DB](infrastructure/shared/project/templates/backend/src/db/).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| M01 | P1 / M | Compléter les probes de tables/colonnes par des essais de contraintes : unicité, nullabilité, références et domaines explicitement requis. Vérifier également les types de valeurs relues. | Écart entre schéma déclaré et DDL réellement appliqué. |
| M02 | P1 / M | Valider les données prérequises après initialisation : identités, relations, encodage des mots de passe et absence des résultats qui doivent être créés par When. | Fixtures manquantes ou contaminantes, et indépendance des scénarios. |
| M03 | P2 / E | Tester de vraies migrations sur bases existantes plutôt qu'une simple initialisation avec tables absentes. Ajouter, renommer et retirer un champ sur copies de bases peuplées. | Conservation des données, compatibilité des consommateurs et reprise après échec. |
| M04 | P1 / M | Injecter un échec au milieu d'une opération multi-écriture et vérifier son atomicité. Tester séparément initialisation, création métier et données prérequises. | Absence d'état partiel et diagnostic de la transaction fautive. |
| M05 | P2 / M | Exercer concurrence et répétitions : deux inscriptions du même identifiant, doubles soumissions, accès concurrents à une ressource. Attendre les garanties réellement spécifiées. | Doublons, verrous non gérés et invariants métier violés. |
| M06 | P2 / M | Générer des volumes de données réalistes et examiner les requêtes lentes et leurs plans. Comparer les index proposés aux besoins prouvés des parcours. | Latence, taille de la base, coût des écritures et stabilité des résultats. |

Préserver les vérifications déjà présentes : initialisation répétée, table manquante, redémarrage du serveur, clés étrangères et conservation des données existantes.

### N — Backend et cohérence des interfaces

Points d'intégration : [06_design_backend_apis.py](06_design_backend_apis.py), [08_implement_backend_tdd.py](08_implement_backend_tdd.py), [backend/runtime.py](infrastructure/stages/backend/runtime.py), [types.ts](infrastructure/shared/project/templates/backend/src/api/types.ts).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| N01 | P1 / M | Vérifier les requêtes et réponses HTTP observées contre les schémas du contrat. Tester champs absents, types incorrects, statuts et réponses vides. | Incompatibilités d'interface détectées et rejets non justifiés par le contrat. |
| N02 | P1 / M | Compiler les conventions d'authentification en cas de test communs : credential absent/inconnu, compte attendu, déconnexion et absence de secret exposé. | Divergences entre API partageant la même convention. |
| N03 | P1 / M | Construire une table des branches de chaque API à partir des préconditions/postconditions, puis suivre les branches effectivement exercées. | Rejets et garanties sans écriture couverts, sans inventer des politiques supplémentaires. |
| N04 | P2 / E | Générer types et client HTTP à partir du contrat canonique, puis comparer avec leur rédaction libre. Garder la logique métier dans le code applicatif. | Erreurs de transport, paramètres oubliés et coût des changements de contrat. |
| N05 | P1 / M | Vérifier automatiquement l'enregistrement des routes et leurs collisions, notamment paramètres dynamiques, fallback API et ordre des middlewares. | Routes inaccessibles, doublons et comportements antérieurs cassés. |
| N06 | P2 / M | Ajouter un profil optionnel de robustesse HTTP : entrée trop volumineuse, erreur DB, réponse mal formée et donnée privée. Distinguer exigence métier et règle de qualité additionnelle. | Pannes non maîtrisées, réponses incohérentes et coût du profil. |

Les contrôles additionnels doivent être annoncés dans le profil d'évaluation. Une politique inventée par un test ne devient pas une exigence utilisateur.

### O — Interface, vision et interactions

Points d'intégration : [vision.py](infrastructure/shared/models/vision.py), [ui/design.py](infrastructure/stages/frontend/ui/design.py), [ui/testing.py](infrastructure/stages/frontend/ui/testing.py), [triggers/implementation.py](infrastructure/stages/frontend/triggers/implementation.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| O01 | P1 / M | Ajouter une évaluation visuelle séparée : régions, proportions, typographie et couleurs. Comparer rendu/référence selon une grille ; utiliser des snapshots approuvés pour les régressions ultérieures. | Qualité visuelle mesurée et désaccord avec l'évaluation humaine. |
| O02 | P2 / M | Tester plusieurs dimensions de viewport, zooms et longueurs de texte. Évaluer lisibilité, débordements et accès aux actions sans imposer une mise en page absente des exigences. | Contrôles inutilisables ou masqués et régressions entre formats. |
| O03 | P1 / M | Vérifier navigation clavier, noms accessibles, association label/champ, focus et messages d'erreur. Réutiliser les libellés exacts imposés. | Défauts d'accessibilité et contrats de nommage violés. |
| O04 | P1 / M | Tester états vide, chargement, rejet, données réelles et annulation. Comparer l'UI avant et après chargement sans injecter de faux objets dans la production. | Affichages trompeurs, valeurs par défaut indues et contrôles désynchronisés. |
| O05 | P1 / M | Introduire réponses retardées/inversées, changement rapide d'objet, reload et plusieurs onglets quand le scénario le justifie. Les perturbations restent dans le banc de test. | Écrasements par réponses périmées et incohérences de session ou d'identité. |
| O06 | P1 / M | Rendre systématiques les essais de soumission par clic, Entrée, icône imbriquée et clic rapide. Observer l'opération métier concernée, pas tous les appels réseau. | Mutations envoyées en double et opérations légitimes supprimées par déduplication abusive. |

Les screenshots de référence externes ne sont pas automatiquement des snapshots Playwright directement comparables. Stabiliser navigateur, polices, viewport et données avant d'interpréter les écarts. Playwright propose la comparaison de captures et souligne la dépendance au contexte de rendu : [documentation officielle](https://playwright.dev/docs/test-snapshots).

### P — Isolation, permissions et protection des données

Points d'intégration : [tools/files.py](infrastructure/shared/agent/tools/files.py), [tools/__init__.py](infrastructure/shared/agent/tools/__init__.py), [processes.py](infrastructure/utils/processes.py), [model_io.py](infrastructure/utils/presentation/model_io.py), [package.py](scripts/package.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| P01 | P1 / E | Exécuter le code et les installations générés dans un environnement isolé, avec ressources bornées et sans identifiants du compilateur. Tester lecture de fichier extérieur et dépassement de ressources. | Accès interdits bloqués et temps de mise en route additionnel. |
| P02 | P2 / E | Définir des capacités explicites pour le réseau et les services externes, y compris un éventuel adaptateur MCP. Tester une documentation en lecture seule avant tout service en écriture. | Accès utiles, refus corrects et impossibilité d'élargir les droits par un prompt. |
| P03 | P1 / M | Introduire des instructions malveillantes dans exigences, fichiers, images et messages d'erreur. Vérifier la séparation entre données et instructions, ainsi que les droits effectifs des outils. | Actions non autorisées et altérations des tests de confiance. |
| P04 | P0 / F | Comparer le packaging actuel, qui inclut explicitement .env, à un mode de partage excluant les secrets par défaut. Tester avec des secrets factices et lister le contenu de l'archive. | Aucune valeur sensible factice exportée dans le mode sûr ; contenu attendu conservé. |
| P05 | P1 / M | Figer les dépendances évaluées, contrôler les modifications de manifests et distinguer installation autorisée et dépendance suggérée par le modèle. Tester un nom de paquet inexistant. | Reproductibilité et installations indues, avec compatibilité du build préservée. |
| P06 | P1 / M | Appliquer rétention, filtrage et droits aux logs, captures, archives d'échec et mémoires. Tester la présence de données factices sensibles sans les retirer des preuves métier nécessaires. | Exposition de secrets, utilité du diagnostic et volume conservé. |

La séparation des instructions et des contenus récupérés ne remplace pas l'application des permissions aux outils. L'OWASP décrit cette défense en profondeur pour les systèmes LLM : [Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html).

### Q — Performances et réduction du travail répété

Points d'intégration : [dependencies.py](infrastructure/shared/project/dependencies.py), [backend/testing.py](infrastructure/stages/backend/testing.py), [ui/testing.py](infrastructure/stages/frontend/ui/testing.py), [triggers/testing.py](infrastructure/stages/frontend/triggers/testing.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| Q01 | P1 / F | Ne réinstaller les dépendances et navigateurs que si les empreintes ou la disponibilité changent. Comparer exécutions froides et chaudes. | Durée économisée, installations périmées et reproductibilité. |
| Q02 | P2 / E | Sélectionner les régressions à partir du graphe d'impact pendant les tours locaux, puis maintenir une validation finale complète. Comparer au lancement systématique. | Temps économisé et défauts qui auraient échappé aux checks ciblés. |
| Q03 | P1 / M | Ordonner les checks du moins coûteux au plus coûteux selon leur pouvoir de détection mesuré : structure, compilation, HTTP, navigateur, build. Garder les vérifications finales nécessaires. | Temps jusqu'au feedback utile et défauts détectés par niveau. |
| Q04 | P2 / E | Paralléliser les tâches dont les écritures sont disjointes et les contrats figés, dans des espaces isolés. Sérialiser les fusions et revérifier les consommateurs. | Gain de temps après coordination, conflits et non-déterminisme. |
| Q05 | P2 / M | Extraire des utilitaires récurrents et stables après observation : transport HTTP, dates, validation ou fixtures. Comparer code libre et interfaces de bibliothèque réduites. | Erreurs répétées évitées, réutilisation et rigidité introduite. |
| Q06 | P2 / M | Réduire les démarrages répétés de serveurs durant un même groupe de checks avec reset prouvé de l'état. Comparer au processus neuf par invocation. | Gain de durée et absence de fuite d'état ou d'erreur masquée. |

Les gains de cache et de parallélisme doivent être publiés séparément. Une accélération qui masque une régression ou conserve un état de test invalide n'est pas un gain accepté.

### R — Observabilité et diagnostic du compilateur

Points d'intégration : [model_io.py](infrastructure/utils/presentation/model_io.py), [logging.py](infrastructure/utils/presentation/logging.py), [compiler.py](infrastructure/compiler.py), [git.py](infrastructure/shared/project/git.py).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| R01 | P0 / M | Consolider un registre d'exécution : appels SDK, tentatives HTTP, retries, usage disponible et durée, même sans logs détaillés. Réconcilier les compteurs avec des réponses simulées. | Comptage exact sans doubler les tokens mis en cache ni inventer les usages absents. |
| R02 | P2 / M | Relier compilation, passe, exigence, appel, patch et check par identifiants de trace. Commencer par un export local, puis évaluer un collecteur de traces. | Part des échecs entièrement retraçables et durée de diagnostic. |
| R03 | P1 / M | Produire un tableau comparant statut déclaré, exigences attendues, validations exécutées et acceptation externe. Mettre en évidence le non-vérifié. | Faux succès et omissions visibles sans lire tous les logs. |
| R04 | P1 / F | Classer les échecs avec catégories stables : entrée, IR, récupération, protocole, génération, environnement, comportement et vérification absente. Garder la preuve brute liée. | Part d'erreurs classables, accord des évaluateurs et priorités dégagées. |
| R05 | P1 / M | Produire un paquet de reproduction minimal : versions, entrée de test autorisée, manifeste, diff et commandes fixes ; filtrer les secrets. | Taux de reproduction locale et temps jusqu'à la reproduction. |
| R06 | P2 / M | Générer un bilan de preuve par exigence : artefacts, source, patch, tests exécutés, résultats et limites. Comparer à la lecture des rapports par étape. | Temps de revue et capacité à repérer une exigence sans preuve suffisante. |

OpenTelemetry distingue traces, métriques et logs ; cette séparation peut guider l'instrumentation sans imposer d'emblée une plateforme externe : [Signals](https://opentelemetry.io/docs/concepts/signals/).

### S — Expériences de recherche sur l'architecture

Points d'intégration : [principle.md](principle.md), [compiler.py](infrastructure/compiler.py), [backend/primitives.py](infrastructure/stages/backend/primitives.py), modules de synthèse et de tests.

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| S01 | P3 / E | Faire des ablations : pipeline complet, sans obligations, sans récupération, sans conventions, génération directe. Garder des enveloppes comparables et la même acceptation externe. | Contribution de chaque mécanisme au succès, au coût et aux régressions. |
| S02 | P3 / E | Comparer plusieurs sémantiques d'obligations : lectures minimales, écritures exactes, effets conditionnels, obligations de non-écriture. Conserver la version de chaque politique. | Défauts empêchés et solutions valides injustement rejetées. |
| S03 | P2 / M | Construire une progression de tâches par difficulté : exigence isolée, réutilisation, interaction inter-exigences, projet long et évolution. Localiser la rupture de performance. | Courbes de réussite et coût selon taille et difficulté. |
| S04 | P2 / M | Tester les invariances : renommer des identifiants, changer l'ordre des exigences indépendantes, traduire une description ou reformuler sans changer le sens. | Sensibilité à des transformations qui devraient préserver les résultats. |
| S05 | P3 / E | Comparer réviseur unique, comité réduit et classificateur de pannes entraîné hors ligne sur les traces. Séparer les données d'entraînement du test final. | Gain de diagnostic ou de sélection à budget total égal, hors données d'apprentissage. |
| S06 | P3 / E | Comparer une petite IR opérationnelle pour opérations simples à la génération de code libre actuelle. Commencer par CRUD et transactions, garder les cas complexes libres. | Erreurs évitées, expressivité perdue et coût de maintenance du langage intermédiaire. |

L'ambition de preuve formelle doit préciser son périmètre. Des tests réussis, une IR valide et des ensembles de champs couverts apportent des preuves différentes.

### T — Configuration, usage et maintenance du projet

Points d'intégration : [main.py](main.py), [cli.py](infrastructure/utils/cli.py), [pyproject.toml](pyproject.toml), [README.md](README.md), [tests](tests/), [templates](infrastructure/shared/project/templates/).

| ID | Priorité / effort | Idée et essai concret | Mesure déterminante |
| --- | --- | --- | --- |
| T01 | P1 / M | Centraliser la configuration et proposer des profils explicites : rapide, équilibré, qualité ou hors ligne. Publier les paramètres effectifs dans chaque sortie. | Exécutions comparables, paramètres oubliés et simplicité de reproduction. |
| T02 | P1 / F | Ajouter un diagnostic préalable : versions, imports, outils, accès aux modèles et disponibilité navigateur. Séparer checks locaux gratuits et requête de capacité facultative. | Échecs d'environnement détectés avant les passes coûteuses. |
| T03 | P0 / M | Rendre la suite locale reproductible depuis un checkout propre. Examiner tests et imports obsolètes ; notamment, test_stress_test.py importe un script absent du checkout inspecté. Relever l'erreur réellement exécutée avant correction. | Collecte et exécution déterministes des tests, sans appels modèle réels non annoncés. |
| T04 | P1 / M | Présenter un rapport final orienté décision : ce qui fonctionne, échoue, reste non vérifié, et ce qui peut être repris. Tester sur des rapports partiels. | Temps nécessaire pour comprendre le résultat et choisir la suite. |
| T05 | P3 / E | Tester une seconde pile via un adaptateur défini : templates, contrats, outils et exécuteurs de checks. Réutiliser le même corpus fonctionnel. | Part de logique réutilisable et coût réel de portage sans baisse de validation. |
| T06 | P2 / M | Ajouter des points de clarification ciblés pour contradiction métier, changement incompatible ou blocage hors capacités. Comparer autonomie complète et intervention limitée documentée. | Interventions par réussite, décisions arbitraires évitées et temps humain total. |

Ne pas utiliser la seconde pile ou les intégrations externes comme premier chantier : elles compliquent la mesure tant que le socle n'est pas reproductible.

## Ordre de mise en œuvre proposé

### Vague 1 — Établir une baseline vérifiable

1. T03 : rendre explicite l'état réel de la suite depuis un checkout propre.
2. R01 et L01 : enregistrer les mesures et disposer d'une acceptation externe figée.
3. A01 et J01 : fiabiliser le statut final et les limites d'exécution.
4. B01, C01 et C02 : isoler les erreurs d'entrée, de structure et de référence.

**Livrable attendu :** pour chaque tâche du corpus, savoir ce qui a été tenté, vérifié, dépensé et réellement réussi. Une défaillance connue reste visible dans la baseline jusqu'à sa correction.

### Vague 2 — Réduire les pertes les plus fréquentes

Choisir les pistes à partir des pannes mesurées :

- Beaucoup de recherches ou lectures : E04, F02 et F05.
- Boucles sans progrès : J02 et J03.
- Erreurs d'environnement et temps fixe élevé : T02 et Q01.
- Tests trop faibles : L02, L04 et L06.
- Échec après interruption : A03.
- Données prérequises ou DDL incorrects : M01 et M02.

**Livrable attendu :** comparaisons isolées et reproductibles, avec explication du gain ou de l'absence de gain.

### Vague 3 — Améliorer qualité et coût à budget maîtrisé

Évaluer K01/K02, N01/N03, O01/O03/O06, puis les mémoires et recettes G01/H04 lorsque les traces fournissent des exemples utiles. Tester ensuite les combinaisons qui ont réussi isolément.

**Livrable attendu :** quelques profils sur une frontière qualité/coût/durée, avec limites connues selon les catégories de tâches.

### Vague 4 — Explorer des architectures plus ambitieuses

Tester compilation incrémentale fine, recherche hybride, tâches parallèles, modèles de diagnostic, IR opérationnelle ou seconde pile. Les comparer à la meilleure variante simple disponible.

**Livrable attendu :** décision argumentée de garder, restreindre ou abandonner chaque mécanisme complexe.

## Fiche à remplir pour chaque expérience

Copier ce modèle dans le suivi expérimental. Il décrit une expérience à venir ; il ne correspond pas à une fonctionnalité déjà implémentée.

```yaml
experience:
  id: F02
  titre: Interfaces et extraits avant lecture complete
  statut: proposee
  hypothese: Reduire les sources envoyees sans diminuer la reussite externe
  baseline_commit: a_renseigner
  variante_commit: a_renseigner
  corpus_version: a_renseigner
  suite_externe_version: a_renseigner
  environnement: a_renseigner
  modele_et_version: a_renseigner
  prompts_version: a_renseigner
  changement_unique: a_renseigner
  repetitions: a_definir_avant_lancement
  limites:
    appels_totaux: a_definir
    tokens: a_definir
    duree: a_definir
    cout_si_mesurable: a_definir
  mesure_principale: a_definir
  gain_minimal_utile: a_definir
  regressions_inacceptables:
    - comportement_precedemment_requis_perdu
    - succes_annonce_sans_verification
  controles:
    - memes_taches_et_attentes
    - sorties_et_bases_isolees
    - echecs_et_depassements_conserves
    - variantes_cache_froid_et_chaud_distinguees
  resultats:
    reussites_completes: null
    echecs: null
    non_verifies: null
    cout_par_reussite: null
    duree_mediane: null
    erreurs_de_contexte: null
    incertitude: a_renseigner
  preuves: []
  decision: en_attente
  limites_connues: []
```

### Exemple de décision attendue

Pour F02, ne pas se contenter de « les prompts sont plus courts ». Comparer le taux de réussite externe, les erreurs attribuables à une définition manquante, les appels de lecture supplémentaires et le coût total. Si la réduction de contexte fragilise les tâches longues, limiter la variante aux tâches où elle conserve assez de preuves.

## Pièges à éviter

- **Tout combiner dès le départ.** Impossible ensuite d'attribuer une amélioration au bon mécanisme.
- **Optimiser la réussite annoncée.** Une suite faible ou modifiée peut rendre le rapport meilleur sans améliorer l'application.
- **Oublier les dénominateurs.** Publier exigences attendues, tâches tentées, tests exécutés et validations absentes.
- **Compter uniquement les exécutions réussies.** Cela masque le prix des échecs et des retries.
- **Comparer des budgets différents sans le dire.** Un comité ou plusieurs candidats doivent être comparés à enveloppe totale connue.
- **Faire du modèle son propre oracle unique.** Conserver une acceptation réservée et des défauts injectés interprétables.
- **Traiter la couverture des champs comme une preuve sémantique complète.** Identité, branche, ordre des opérations et persistance exigent aussi des observations.
- **Rendre les tests conformes au code faux.** Une réparation de test doit être justifiée par l'exigence.
- **Transformer les screenshots en données métier.** Les exemples visuels ne prouvent ni un compte existant ni un objet chargé.
- **Optimiser le cache sans invalidation.** Les résultats doivent porter sur la version actuelle des entrées et sources.
- **Accroître les droits pour simplifier une tâche.** Les capacités supplémentaires doivent être explicitement définies et évaluées.
- **Accumuler mémoire, skills et contexte sans sélection.** Mesurer leur apport sur des tâches nouvelles.
- **Généraliser depuis le seul exemple d'authentification.** Publier les résultats par catégorie et complexité.
- **Confondre hypothèse et résultat.** Tant qu'une expérience n'est pas exécutée et comparée, son bénéfice reste supposé.

## Références externes

Ces sources primaires décrivent des mécanismes utiles pour concevoir les essais. Elles ne démontrent pas un gain sur ce compilateur. Les noms de bibliothèques et les architectures proposés restent des options à évaluer.

| Source | Utilisation dans ce document |
| --- | --- |
| [JSON Schema — Objects](https://json-schema.org/understanding-json-schema/reference/object) | C01 : formes de réponse, champs requis et politique sur les propriétés supplémentaires. |
| [Anthropic — Building effective agents](https://www.anthropic.com/research/building-effective-agents) | D03/D06, K01, S05 : variantes d'orchestration et boucles d'évaluation. |
| [Hypothesis — Stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html) | L03 : génération de séquences d'actions et réduction des contre-exemples. |
| [Stryker — Mutant states and metrics](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/) | L02 : distinguer mutants détectés, survivants et résultats non interprétables comme détection métier. |
| [Playwright — Visual comparisons](https://playwright.dev/docs/test-snapshots) | O01 : comparaison de captures et stabilisation de l'environnement. |
| [OWASP — LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) | P02/P03 : contenus non fiables, périmètres d'outils et défense en profondeur. |
| [OpenTelemetry — Signals](https://opentelemetry.io/docs/concepts/signals/) | R02 : séparation traces, métriques et logs. |

Les constats propres au dépôt sont issus des fichiers locaux liés dans les sections correspondantes.

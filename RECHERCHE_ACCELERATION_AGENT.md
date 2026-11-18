# Accélérer l’agent et réduire ses tokens : ce que dit la recherche

Rédigé le 16 novembre 2026, après un run Arcbench toujours en cours au bout d’une heure.
Chaque méthode est rattachée à ce qu’on observe dans ce run et à son état dans le moteur.

## 1. Ce que montre le journal du run (18:54 → 19:55, inachevé)

| Constat | Mesure dans le journal | Cause dans le moteur |
| --- | --- | --- |
| Contexte renvoyé à chaque requête | dès 19:15, compaction à presque chaque requête, de ~310 Ko à ~300 Ko | la compaction s’arrêtait juste sous son seuil : chaque requête renvoyait ~75 000 tokens et cassait le cache |
| Une requête toutes les 20 à 60 s | ~130 appels d’outils en 61 min, en général un par réponse | temps de réponse du modèle sur un très long contexte |
| Commande bloquée 10 minutes | `run_command` de 19:21:37 à 19:31:38 | délai par défaut de 600 s ; un serveur lancé dans `run_command` ne rend jamais la main |
| Aucune proposition de fin en une heure | 20 `run_command`, 9 `http_request`, 5 `process_start`, des requêtes en base, le navigateur | l’agent teste à la main au lieu de laisser la vérification de l’hôte le faire |

La génération elle-même (19:00 → 19:08) a pris moins de 10 minutes ; le reste est du
test manuel et de la correction à tâtons, sur un contexte de plus en plus lourd.

## 2. Méthodes tirées de la recherche, classées par effet attendu ici

### 2.1 Masquage des anciennes observations (implémenté)

- **Source** : Lindenbauer et al., *The Complexity Trap* (NeurIPS 2025, atelier DL4Code).
  Sur SWE-bench Verified, remplacer les anciennes observations par un marqueur divise
  le coût par deux environ par rapport à l’agent brut, avec un taux de résolution égal
  ou légèrement supérieur à un résumé par LLM. Le résumé allonge les trajectoires
  d’environ 15 % (Gemini 2.5 Flash). La taille de la fenêtre doit être réglée par agent.
- **AgentDiet** (Trajectory Reduction, FSE 2026) va dans le même sens : en retirant
  l’information inutile, redondante ou périmée de la trajectoire, les tokens d’entrée
  baissent de 40 à 60 % et le coût de 21 à 36 %, à résultat égal.
- **Dans le moteur** : au-delà des 10 derniers lots d’appels (`loop.observation_window`),
  les résultats d’outils et le texte des fichiers écrits sont remplacés par un marqueur
  qui garde le chemin et l’identifiant de l’artefact. Le raisonnement et les actions
  restent. Le masquage se fait par blocs de 24 Ko au moins, pour ne pas casser le cache à
  chaque requête. La compaction descend maintenant à 55 % de son seuil, et le contexte
  maximal passe de 400 à 240 Ko.

### 2.2 Laisser la vérification externe trouver les erreurs (implémenté en partie)

- **TDDev** (Wan et al., ASE 2026) : des tests d’acceptation écrits à partir des
  exigences avant le code, puis des échecs observés dans le navigateur traduits en
  rapports de réparation structurés. Gain de 15,5 à 23,7 points de précision sur
  20 applications web complètes, avec un modèle assez capable.
- **FullStack-Agent** (Lu et al., 2026) : sans outil de test du backend, l’agent backend
  passe de 74,9 à 115,5 itérations en moyenne. Un retour de test outillé et précis
  économise des tours.
- **Tokenomics** (Salim et al., 2026) : dans un développement multi-agents, la phase de
  revue et de vérification consomme 59 % des tokens, plus que la génération initiale.
- **Dans le moteur** : la vérification de l’hôte joue déjà ce rôle (tests Playwright, retour
  de symptômes précis). Le problème est que l’agent ne la déclenche pas. Corrigé :
  - consigne explicite : écrire toute l’application, passer `verify_application`, puis
    proposer la fin sans tester chaque parcours à la main ;
  - aucune limite de temps, de requêtes, d’appels d’outils, de tokens ni de tours de
    vérification : ces limites grandissent avec la taille du site et sont à 0 (aucune)
    dans le profil. Une boucle de réparation s’arrête toujours quand elle stagne (mêmes
    échecs, aucune source modifiée). Avec `--max-seconds`, l’agent reçoit en plus des
    rappels à 50 % et 80 % de son temps de travail.
- **Reste à faire** : lancer la vérification de l’hôte automatiquement dès que le
  premier build complet passe, sans attendre la proposition de l’agent.

### 2.3 Arrêter tôt ce qui ne progresse plus

- **EET** (Guo et al., Findings ACL 2026) : arrêter tôt génération et sélection de
  correctifs grâce à l’expérience de runs passés : coût −32 % en moyenne (−19 à −55 %),
  au plus −0,2 point de résolution.
- **The Danger of Overthinking** (Cuadron et al., 2025) : sur 4 018 trajectoires
  SWE-bench, la « paralysie d’analyse » (planifier sans agir) corrèle avec l’échec ; choisir
  la trajectoire la moins « sur-réfléchie » améliore de près de 30 % en coûtant 43 % de
  moins. Le raisonnement `low` de notre profil va dans ce sens.
- **Dans le moteur** : bornes de temps et rappels ci-dessus ; détecteur de répétitions
  existant. **Non fait** : une mémoire d’expérience entre runs, qui demande d’abord des
  traces de vrais runs.

### 2.4 Paralléliser les appels indépendants (implémenté, proposition 1)

- **LLMCompiler** (Kim et al., ICML 2024) : planifier un graphe d’appels et exécuter en
  parallèle les appels indépendants : jusqu’à 3,7× plus rapide et 6,7× moins cher que
  ReAct sur des tâches très parallèles, gain plus modeste sinon.
- **Dans le moteur** : outils groupés et appels en lecture seule exécutés en parallèle.
  Le journal montre que l’agent groupe peu après les premières minutes ; le gain dépend
  du modèle.

### 2.5 Cache de préfixe du fournisseur

- **Don’t Break the Cache** (Lumer et al., 2026) : sur plus de 500 sessions d’agent, le
  cache de prompt réduit le coût de 41 à 80 % et le temps jusqu’au premier token de 13 à
  31 %, à condition de garder le début du prompt stable et de ne pas y mettre de
  contenu dynamique. Un cache mal conçu peut même ralentir.
- **Dans le moteur** : instructions et schémas stables ; élagage et masquage par gros
  blocs. La compaction à chaque requête du run cassait le cache à chaque fois : c’est
  corrigé. Le taux réel (`cached_input_ratio` dans `run.json`) reste à lire au prochain run.

### 2.6 Spécialiser au lieu de laisser l’agent tout explorer

- **Agentless** (Xia et al., 2024) : un pipeline fixe localisation → réparation →
  validation, sans boucle d’agent, a obtenu le meilleur score open source de SWE-bench
  Lite de l’époque pour 0,70 $ par issue environ. Les auteurs montrent que les outils mal
  définis d’un agent coûtent des requêtes inutiles.
- **Dans le moteur** : squelette enrichi (proposition 3, terminée dans cette version)
  avec session, mots de passe, erreurs HTTP, client d’API, routeur et formulaires déjà
  testés, et un `package-lock.json` qui fixe les versions installées. Moins de code à
  écrire, donc moins de tokens de sortie, les plus lents.

### 2.7 Peu applicable ici

- **Actions spéculatives** (Ye et al., 2025 ; PASTE, 2026) : prédire et pré-exécuter les
  prochains appels d’outils. Gain annoncé de 6 à 21 % du temps total, jusqu’à 55 % du
  temps des outils. Chez nous l’essentiel du temps est l’attente du modèle et des tests ;
  le gain serait faible pour une complexité élevée.
- **Minification du code** dans le contexte : −42 % de tokens d’entrée mais −12 points
  de résolution (2026). À éviter.

## 3. Ce que change cette version (agentnewv1.3)

1. Compaction avec marge (55 % du seuil), contexte maximal 240 Ko.
2. Masquage des observations et du texte écrit au-delà des 10 derniers lots d’appels.
3. `run_command` : 120 s par défaut ; un serveur y est refusé, avec renvoi vers
   `process_start`.
4. Consigne de fin rapide. Limites qui grandissent avec la taille du site retirées (temps,
   requêtes, appels d’outils, tokens, tours de vérification, nombre de tests générés) ;
   le délai de la suite de tests s’allonge avec le nombre de tests.
5. Proposition 3 : squelette enrichi et `package-lock.json`.

Aucune de ces mesures n’a été vérifiée avec le vrai modèle. Envoyez la ligne
`Run breakdown:` du prochain run : elle donne la part du modèle, des outils et de la
vérification, et le taux de cache.

## Sources

- Lindenbauer et al., *The Complexity Trap: Simple Observation Masking Is as Efficient as LLM Summarization for Agent Context Management*, 2025. https://arxiv.org/abs/2508.21433
- *Reducing Cost of LLM Agents with Trajectory Reduction* (AgentDiet), 2025. https://arxiv.org/abs/2509.23586
- Guo et al., *EET: Experience-Driven Early Termination for Cost-Efficient Software Engineering Agents*, 2026. https://arxiv.org/abs/2601.05777
- Cuadron et al., *The Danger of Overthinking: Examining the Reasoning-Action Dilemma in Agentic Tasks*, 2025. https://arxiv.org/abs/2502.08235
- Kim et al., *An LLM Compiler for Parallel Function Calling*, 2023. https://arxiv.org/abs/2312.04511
- Lumer et al., *Don’t Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks*, 2026. https://arxiv.org/abs/2601.06007
- Xia et al., *Agentless: Demystifying LLM-based Software Engineering Agents*, 2024. https://arxiv.org/abs/2407.01489
- Wan et al., *From Runnable to Shippable: Multi-Agent Test-Driven Development for Generating Full-Stack Web Applications from Requirements* (TDDev), 2026. https://arxiv.org/abs/2605.17242
- Lu et al., *FullStack-Agent: Enhancing Agentic Full-Stack Web Coding*, 2026. https://arxiv.org/abs/2602.03798
- Salim et al., *Tokenomics: Quantifying Where Tokens Are Used in Agentic Software Engineering*, 2026. https://arxiv.org/abs/2601.14470
- Ye et al., *Speculative Actions: A Lossless Framework for Faster Agentic Systems*, 2025. https://arxiv.org/abs/2510.04371
- *Act While Thinking: Accelerating LLM Agents via Pattern-Aware Speculative Tool Execution* (PASTE), 2026. https://arxiv.org/abs/2603.18897
- *Reducing Token Usage of State-in-Context Agents using Minification*, 2026. https://arxiv.org/abs/2606.01326
- Lu et al., *WebGen-Bench*, 2025. https://arxiv.org/abs/2505.03733

# Partie 2 — réduire le temps (après la v1.3)

Résultat de la v1.3 sur Arcbench : 5/5 tests, 1,31 CNY (contre 3,43 en v1.0), 52,3 min
(contre 46 min). Les tokens ont baissé, pas le temps. Repères publiés pour une petite
application web générée par un seul agent : 6 à 14 min pour Cursor, Copilot et Windsurf
(étude empirique 2026), 11 à 21 min pour les meilleurs modèles de Vibe Code Bench, jusqu’à
76 min pour GPT-5.3-Codex. Il reste donc une marge importante.

Sans la ligne `Run breakdown:` du run v1.3, on ne sait pas quelle part va à l’attente du
modèle, aux outils ou à la vérification. Le classement ci-dessous repose sur le journal
du run v1.2, où le modèle mettait 20 à 60 s par réponse.

## Méthodes, de la plus prometteuse à la moins prometteuse

| # | Méthode | Source | Gain publié | État |
| --- | --- | --- | --- | --- |
| 1 | Préparer pendant que le modèle réfléchit | PASTE (2026) | −43,5 % du temps de tâche quand les outils pèsent 35 à 61 % du temps | **fait (v1.4)** pour l’installation et le lanceur de tests |
| 2 | Paralléliser l’écriture entre sous-agents, regroupés par cohésion | Co-Coder (2026) | jusqu’à 2,1× plus rapide, +14 % de réussite, −35 % de coût | **fait (v1.6)** |
| 3 | Lancer la vérification de l’hôte dès le premier build complet | TDDev (ASE 2026), Tokenomics (2026) | +15,5 à 23,7 points de précision ; la vérification pèse 59 % des tokens | proposé |
| 4 | Raisonnement minimal par défaut, relevé seulement après un échec | *What Effort Level Should I Choose?* (2026), Confucius (2025) | un effort plus élevé coûte 2,5 à 3× plus sans gain fiable | proposé, à mesurer |
| 5 | Exécuter les appels d’outils dès qu’ils sont émis (réponse en flux) | LLMCompiler (2023), PASTE (2026) | jusqu’à 1,35× face aux appels parallèles natifs | proposé |
| 6 | Tests d’acceptation sur plusieurs workers Playwright | documentation Playwright | dépend du nombre de tests | proposé, risque d’interférences |
| 7 | Éditions par remplacement plutôt que réécriture complète | Aider, SWE-Edit (2026) | gain faible ; la réécriture reste plus fiable pour les fichiers courts | déjà en place |

### 1. Préparer pendant que le modèle réfléchit (fait)

PASTE et les « actions spéculatives » exécutent à l’avance les appels d’outils prévisibles.
Chez nous, deux opérations sont certaines dès le départ : l’installation des dépendances
du squelette (lockfile connu, environ 100 s sous Linux) et l’installation du lanceur de
tests Playwright. Elles démarrent maintenant en arrière-plan au début du run. L’agent et
la vérification réutilisent le résultat ; un verrou empêche deux installations
simultanées. Si l’agent modifie un `package.json` pendant l’installation, celle-ci n’est
pas considérée comme à jour et sera refaite.

### 2. Sous-agents parallèles regroupés par cohésion

Co-Coder montre que paralléliser naïvement par fichier accélère (×1,56) mais fait monter
le coût de 60 % et peut dégrader la qualité, tandis que regrouper les fichiers fortement
liés avant de les répartir atteint ×2,1 avec une meilleure réussite. Les « équipes
d’agents » de Claude Code étaient les plus rapides sur certains tests mais moins bonnes.

Application ici : une première phase écrit le contrat commun (tables SQL, routes de l’API,
types partagés, liste des pages) ; puis le backend et chaque groupe de pages liées sont
écrits par des sessions parallèles au contexte réduit ; enfin la session principale
intègre et vérifie. C’est le plus gros gain possible sur la phase d’écriture, et le
changement le plus risqué : à faire seulement si le détail du temps montre que
l’écriture domine.

**État (v1.6) : implémenté, effet non mesuré.** Outil `delegate_tasks` : l’agent principal
écrit le contrat commun, puis confie jusqu’à 4 tâches à des sous-agents qui tournent en
même temps, chacun avec son propre client du modèle. Chaque tâche ne peut écrire que dans
ses chemins (fichiers ou dossiers disjoints, vérifiés avant toute requête) ; les
sous-agents lisent tout l’espace de travail mais n’ont aucune commande (ni npm, ni
serveur, ni vérification). Ils reçoivent le contrat, le texte de leurs exigences et le
guide des briques. Leur coût (requêtes, tokens, appels d’outils) est compté dans le run
(`budget.requests.subagent`). L’échec d’un sous-agent n’annule pas les autres. L’agent
principal intègre ensuite (routes, navigation) et vérifie. La consigne lui demande de
déléguer pour toute application qui a des parties indépendantes. Le journal du runner
affiche les outils de chaque sous-agent (`[nom de la tâche] tool …`).

Limite : un découpage maladroit (fichiers liés répartis entre tâches) oblige l’agent
principal à corriger l’intégration, ce qui peut annuler le gain. C’est le risque relevé
par Co-Coder pour le découpage naïf.

### 3. Vérification de l’hôte au premier build complet

TDDev montre qu’un retour de tests d’acceptation exécutés dans le navigateur, traduit en
rapport de réparation structuré, vaut mieux que l’auto-test de l’agent. Chez nous, ce
retour n’arrive que lorsque l’agent propose la fin ; avant, il teste à la main. Proposition :
dès que `verify_application` (typage, build, tests) passe pour la première fois, l’hôte
lance la suite d’acceptation et renvoie les échecs immédiatement.

### 4. Raisonnement minimal par défaut

Sur Terminal-Bench et SWE-Bench Pro, passer d’un effort de raisonnement bas à très haut
multiplie le coût par 2,5 à 3 et augmente l’auto-vérification, sans amélioration
fiable du résultat. Le profil est déjà à `low`. Essai à faire : `none` pour l’écriture, `low`
après un échec de vérification. Un seul run comparé suffit à voir l’effet sur le temps,
mais pas sur le taux de réussite.

### 5. Exécution des appels dès leur émission

Aujourd’hui le moteur attend la réponse complète avant d’exécuter le premier appel. En
mode flux, une lecture ou une commande peut démarrer pendant que le modèle écrit encore
les appels suivants. Le gain est réel quand une réponse contient plusieurs appels ou un
long fichier, mais demande d’implémenter le streaming, absent du moteur.

### 6. Plusieurs workers Playwright

Les tests fournis créent des comptes uniques (`newAccount()`), ce qui rend une exécution
parallèle plausible contre un même serveur. Mais un test qui lit des données de départ
modifiées par un autre échouerait au hasard. À n’activer qu’après mesure du temps des
tests dans `budget.timing.verification.acceptance`.

## Ce qu’il faut pour avancer

La ligne `Run breakdown:` (ou `.arc/run.json`) du run v1.3. Si l’attente du modèle domine,
les méthodes 2 et 4 sont prioritaires ; si c’est la vérification, les méthodes 3 et 6 ;
si ce sont les outils, la méthode 1 suffit peut-être.

## Sources (partie 2)

- *Act While Thinking: Accelerating LLM Agents via Pattern-Aware Speculative Tool Execution* (PASTE), 2026. https://arxiv.org/abs/2603.18897
- *When Parallelism Pays Off: Cohesion-Aware Task Partitioning for Multi-Agent Coding* (Co-Coder), 2026. https://arxiv.org/abs/2606.00953
- *SquidAgent: Parallelize Wisely, Coordinate Efficiently*, 2026. https://arxiv.org/abs/2610.08647
- Wan et al., *From Runnable to Shippable* (TDDev), ASE 2026. https://arxiv.org/abs/2605.17242
- Salim et al., *Tokenomics*, 2026. https://arxiv.org/abs/2601.14470
- *What Effort Level Should I Choose? On the Economics of Reasoning Effort in LLM Agents*, 2026. https://www.researchgate.net/publication/416920448
- *Confucius Code Agent: Scalable Agent Scaffolding for Real-World Codebases*, 2025. https://arxiv.org/abs/2512.10398
- Kim et al., *An LLM Compiler for Parallel Function Calling*, 2023. https://arxiv.org/abs/2312.04511
- *SWE-Edit: Rethinking Code Editing for Efficient SWE-Agent*, 2026. https://arxiv.org/abs/2604.26102
- *Generation of Web Apps with Agentic IDEs: An Empirical Assessment*, 2026. https://arxiv.org/abs/2608.20903
- Vibe Code Bench, 2026 (résumé). https://cgr-blog.pages.dev/posts/vibe-code-bench-58-percent-accuracy
- Playwright, *Parallelism*. https://playwright.dev/docs/test-parallel

# Partie 3 — qualité sur un site plus grand (v1.8)

Run v1.3 sur un site de 12 scénarios (gestion de livres et de pages) : 6/12 sur Arcbench,
alors que les 12 tests générés par l’hôte passaient. Ce que les exigences et les logs
montrent, et les corrections génériques qui en découlent :

1. **Contrat d’interface explicite.** Les exigences nomment les éléments que les tests
   localisent, sous la forme `"Book list"(role=region)` ou `Page list (region)`. L’hôte
   extrait maintenant ces paires rôle/nom (`infrastructure/requirements/contract.py`,
   sans appel au modèle) ; l’agent les reçoit dans son premier message sous forme de
   localisateurs exacts, et le générateur de tests de l’hôte doit les utiliser tels quels.
2. **Tests en parallèle sur une base partagée.** Les exigences l’annoncent (« test names
   append run, worker and case identity »). Les tests locaux tournent maintenant sur
   3 workers (`acceptance.workers`), ce qui fait apparaître les listes paginées ou
   tronquées et les problèmes de concurrence avant la livraison.
3. **Règles de livraison** ajoutées aux instructions : textes exacts, champ décrit par un
   texte d’aide nommé et pourvu de ce placeholder, aucune pagination non demandée,
   navigation exigée toujours appliquée, jamais de cas particulier pour satisfaire un test.

Ces règles ne visent pas ce site : elles s’appliquent à toute exigence rédigée de cette
façon. Effet non mesuré.


# Partie 4 — état de la recherche fin 2026, appliqué à nos runs (après la v1.16)

Les quatre derniers runs montrent trois problèmes :
- sur les gros sites, l'agent relit sans écrire (0/28 et 0/35) ;
- sur BookStack, les tests locaux passent alors que les tests cachés plafonnent à 6/12 ;
- la vérification boucle sans fin sur un test généré défectueux.

Les travaux ci-dessous sont classés par gain attendu sur ces problèmes. Les chiffres viennent des résumés des papiers, pas d'une lecture intégrale, et sont ceux qu'annoncent leurs auteurs.

## 1. Taux de réussite : nos tests locaux ne sont qu'un juge parmi d'autres

- **Vibe Code Bench** (Tran et al., 2026 ; 100 applications, 964 parcours) : le meilleur modèle atteint 58 à 62 %.
  - Le meilleur prédicteur de réussite est l'auto-test dans le navigateur pendant la génération : corrélation de 0,72, qui tient même en contrôlant le temps passé. Le volume d'édition prédit moins bien.
  - Surtout, **le choix de l'évaluateur change le résultat** : les évaluateurs ne s'accordent qu'entre 31,8 et 93,6 % sur chaque étape.
- **All Smoke, No Alarm** (2026) : sur 86 156 fichiers de tests écrits par des agents, 80,2 % ont des assertions faibles ou absentes. D'autres études montrent que des assertions générées encodent souvent le comportement observé au lieu du comportement attendu.
- **Audit des boucles de génération de tests** (2026) : comparés à un panel de trois implémentations acceptées, les résultats attendus générés ne concordent que dans 28 à 50 % des cas. Les « fautes » détectées contre une seule implémentation sont souvent fausses.
- **IWC-Bench** (Tencent, 2026) : un explorateur parcourt l'application sans voir les critères d'acceptation, et la notation se fait séparément. La couverture indique ce qui n'a pas été exploré.

**Pour nous.** Notre unique générateur de tests est un juge avec ses propres biais, et l'agent plie l'application pour lui plaire. Pistes :

1. **Deux générateurs indépendants** (deux prompts ou deux températures). Ne renvoyer à l'agent comme « échec » qu'un défaut constaté par les deux ; un désaccord devient « test douteux », signalé sans exiger de changement.
2. **Assertions limitées aux résultats décrits par l'exigence** (le texte du `Then`). C'est déjà dans les consignes ; on peut le vérifier statiquement en exigeant que chaque test contienne au moins une assertion citant un texte du `Then`.
3. **Exploration libre avant les tests** : une passe clique chaque lien et chaque bouton de chaque page déclarée, et signale les erreurs (404, exception, bouton sans effet). Elle ne dépend d'aucun test généré, donc ne pousse à aucun contournement.

## 2. Contexte : évincer d'abord ce qui est déjà inscrit dans l'environnement

- **Beyond Compaction, méthode CWL** (Semenov et Dorofeev, 2026) : au lieu de résumer, l'agent annote son travail en épisodes typés et liés entre eux.
  - Quand le budget est dépassé, une règle déterministe, sans appel au modèle, évince d'abord **les épisodes dont l'effet est déjà persisté dans l'environnement** (un fichier écrit, par exemple).
  - Elle garde les tours de l'utilisateur et le contexte sur lequel l'agent raisonne encore.
  - Résultat annoncé : 89 tâches de suite et 80 M de tokens, sans perte de précision.
- **Context-Folding** (Sun et al., 2025) : `branch` ouvre un sous-contexte pour une sous-tâche, et `return(message)` le replie en un court résumé. Réussite égale à celle de ReAct avec un contexte actif **10 fois plus petit**, et meilleure que la compaction par résumé.
- **ACE** (Zhang et al., ICLR 2026) : le contexte s'enrichit par petites entrées (« deltas ») plutôt que par réécriture complète, car les réécritures successives le dégradent en résumés pauvres. Gain annoncé : +10,6 % sur des tâches d'agent.
- **Self-Compacting Agents et AutoCompact** (2026) : compacter quand le budget est presque plein ignore l'état de la trajectoire ; il vaut mieux compacter aux **frontières de tâche**.

**Pour nous.**

1. **Un journal d'implémentation tenu par l'hôte.** À chaque écriture, l'hôte note quel fichier touche quelles routes, tables et exigences (déduit des chemins, des déclarations `interface_write` et de la todo). Ce journal survit à la compaction : on y ajoute des entrées sans jamais le réécrire, comme dans ACE. L'agent sait ainsi ce qui est fait sans relire.
2. **Une éviction à la manière de CWL.** À la compaction, retirer d'abord les lectures de fichiers que l'agent a réécrits depuis, puis les écritures elles-mêmes (le fichier fait foi), avant de toucher aux exigences et au raisonnement récent.
3. **Compacter aux frontières de section** (une tâche de la todo passée à « done », une vérification réussie) plutôt qu'à un seuil d'octets. On perd moins en cours de tâche et on casse moins souvent le cache du fournisseur.
4. **Une section par sous-contexte replié** (Context-Folding avec nos sous-agents). Pour un gros site, chaque section est traitée dans un sous-contexte qui revient avec un résumé de quelques lignes. `delegate_tasks` existe déjà ; il faut que le premier message le rende évident.

## 3. Planifier avant d'écrire

- **Spec Kit Agents** (2026) : le cycle Specify → Plan → Tasks → Implement produit SPEC.md, PLAN.md (avec les fichiers touchés) et TASKS.md avant la première ligne de code.
- **CodeTeam** (2026) : une planification d'architecture ancrée dans le contexte fait passer la validité structurelle de 0,78 à 0,90.
- **ViBench** (Replit, 2026) : étendre une base stable est plus facile que partir de zéro, et les erreurs s'accumulent quand le modèle étend son propre code.

**Pour nous.** Une première requête courte produit le **plan de l'application** : pages et routes, tables, API, et quelle exigence va où. Il reste dans le contexte permanent pendant tout le run. Il remplace la relecture des exigences pendant l'écriture, sert de contrat commun aux sous-agents et donne un squelette stable que l'agent étend ensuite section par section.

## 4. Visuel : utile, mais secondaire pour des tests fonctionnels

- **UI2App** (2026) : la fidélité visuelle prédit mal la justesse des interactions. Le modèle le plus fidèle visuellement est environ 4,5 fois moins bon en interactions que le meilleur sur ce critère.
- **RILA** (2026) : une boucle exécuter → critiquer → éditer dans un vrai navigateur. Avec une bonne critique, un modèle de 9 milliards de paramètres bat de bien plus gros modèles qui génèrent en un seul coup.
- **VisRefiner** (2026) : le modèle apprend des différences visuelles entre son rendu et la maquette.

**Pour nous.** Garder le retour visuel de la v1.15 limité à un seul tour, puisque les tests cachés sont fonctionnels. La boucle exécuter → critiquer de RILA sert davantage aux interactions (l'exploration du § 1, piste 3) qu'aux pixels.

## 5. Coût : le bon modèle au bon endroit

- **Routage par sous-agent** (retours d'expérience 2026) : donner un modèle moins cher aux sous-agents, à la génération et à la relecture de tests est le gain le plus simple. Un mauvais routage coûte en reprises. Il faut mesurer le **coût par résultat accepté**, pas le coût par requête.
- **Sélection parmi plusieurs candidats** (SWE-World, tournois récursifs, 2026) : +7 à +13 points sur SWE-bench, mais le coût est multiplié d'autant. Hors de propos tant qu'un seul run dure 30 à 60 minutes.

**Pour nous.** `deepseek-flash` est déjà un modèle économique ; le principal levier reste de ne plus brûler de requêtes en boucle (v1.16). À tester ensuite : un raisonnement `none` réservé à la génération et à la relecture des tests de l'hôte (des tâches courtes et cadrées), en gardant `low` pour l'agent.

## Ordre proposé

| # | Changement | Problème visé | Source principale |
|---|---|---|---|
| 1 | Deux générateurs de tests ; échec seulement s'ils concordent | plafond à 6/12, contournements | Vibe Code Bench, audits d'oracles |
| 2 | Plan de l'application en début de run, permanent | relectures, cohérence des gros sites | Spec Kit, CodeTeam |
| 3 | Journal d'implémentation tenu par l'hôte + éviction à la CWL | boucles de relecture, tokens | CWL, ACE |
| 4 | Exploration automatique des liens et boutons | pannes visibles sans test | IWC-Bench, RILA |
| 5 | Compaction aux frontières de section | pertes en cours de tâche, cache cassé | AutoCompact, Self-Compacting |
| 6 | Raisonnement `none` pour les requêtes de test de l'hôte | coût, temps | retours d'expérience sur le routage |

## Sources (partie 4)

- Tran et al., *Vibe Code Bench: Evaluating AI Models on End-to-End Web Application Development*, 2026. https://arxiv.org/abs/2603.04601
- *All Smoke, No Alarm: Oracle Signals in Agent-Authored Test Code*, 2026. https://arxiv.org/html/2606.18168v1
- *Auditing and Decomposing Feedback-Driven Evolution in LLM Test Generation under the Oracle Problem*, 2026. https://arxiv.org/abs/2608.19626
- *IWC-Bench: Evaluating Web Application Generation from a Software Testing Perspective*, 2026. https://arxiv.org/abs/2609.15387
- Semenov et Dorofeev, *Beyond Compaction: Structured Context Eviction for Long-Horizon Agents*, 2026. https://arxiv.org/abs/2606.11213
- Sun et al., *Scaling Long-Horizon LLM Agent via Context-Folding*, 2025. https://arxiv.org/abs/2510.11967
- Zhang et al., *Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models*, ICLR 2026. https://arxiv.org/abs/2510.04618
- *Self-Compacting Language Model Agents*, 2026. https://arxiv.org/pdf/2606.23525
- *AutoCompact: Learning When to Compact Context in Long-Horizon Coding Agents*, 2026. https://arxiv.org/abs/2610.02163
- *CliffCompaction: Cost-Efficient Compaction for Long-Horizon Coding Agents*, 2026. https://arxiv.org/pdf/2609.26779
- *Spec Kit Agents: Context-Grounded Agentic Workflows*, 2026. https://arxiv.org/abs/2604.05278
- *CodeTeam: An LLM-Powered Multi-Agent Framework for Repository-Level Code Generation*, 2026. https://arxiv.org/pdf/2606.22082
- *UI2App: Benchmarking Visual Interaction Inference in Executable Web Application Generation*, 2026. https://arxiv.org/pdf/2607.06306
- *Rendering-in-the-Loop: An Execution-Driven Agent for Interactive Web Development* (RILA), 2026. https://arxiv.org/pdf/2609.02088
- *VisRefiner: Learning from Visual Differences for Screenshot-to-Code Generation*, 2026. https://arxiv.org/abs/2602.05998
- *SWE-World: Building Software Engineering Agents in Docker-Free Environments*, 2026. https://arxiv.org/pdf/2602.03419
- *Scaling Test-Time Compute for Agentic Coding*, 2026. https://arxiv.org/abs/2604.16529
- Retours d'expérience sur le routage de modèles : https://getunblocked.com/blog/model-routing-coding-agents et https://jfrog.com/blog/why-model-routing-backfires

# Propositions d’amélioration après la version 1.0

Référence mesurée sur Arcbench (version 1.0, modèle `deepseek-flash`, raisonnement `low`) :

| Tests réussis | Coût | Durée |
| --- | --- | --- |
| 5/5 | 3,43 CNY | 46 min 03 s |

Objectif : moins de tokens, moins de temps, et un taux de réussite au moins égal sur
d’autres cas que celui-ci.

**Limite de ce document.** La trace du run Arcbench (`events.jsonl`, `run-summary.json`)
n’est pas disponible localement. Le classement ci-dessous repose donc sur la lecture du
code du moteur et non sur une décomposition mesurée du run. Les gains sont donnés en
ordre de grandeur (fort, moyen, faible), jamais en pourcentage. La proposition 0 sert à
remplacer ces estimations par des mesures.

## Vue d’ensemble

Classement par gain attendu, tous axes confondus, pondéré par le risque.

| # | Proposition | Tokens | Temps | Réussite | Effort | Risque |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Mesurer où partent le temps et les tokens (préalable) | — | — | — | faible | nul |
| 1 | Regrouper les actions : moins d’allers-retours avec le modèle | fort | fort | neutre | faible | faible |
| 2 | Alléger le contexte renvoyé à chaque requête | fort | moyen | neutre | moyen | moyen |
| 3 | Squelette d’application plus complet et dépendances pré-résolues | moyen | fort | moyen | moyen | faible |
| 4 | Vérification hôte plus courte | faible | fort | neutre | moyen | faible |
| 5 | Contrat d’interface extrait des tests fournis, donné dès le départ | moyen | moyen | fort | moyen | à trancher |
| 6 | Contrôles rapides automatiques avant la proposition de fin | moyen | moyen | moyen | faible | faible |
| 7 | Carte du code et recherche ciblée (« RAG » léger) | moyen | faible | faible | moyen | faible |
| 8 | Sous-agents parallèles pour les parties indépendantes | incertain | fort | risque | élevé | élevé |
| 9 | Raisonnement adaptatif et routage de modèles | moyen | moyen | moyen | moyen | moyen |
| 10 | Mémoire des erreurs récurrentes entre applications | faible | faible | moyen | moyen | moyen |

Les propositions 1 à 4 ne changent pas ce que l’agent produit : elles sont à faire
d’abord. Les propositions 5, 8 et 9 changent son comportement et doivent être
comparées à la version 1.0 sur plusieurs cas avant d’être retenues.

## 0. Mesurer avant de modifier (préalable)

Un seul run sur un seul cas ne dit ni où part le temps, ni si un changement améliore le
taux de réussite : 5/5 est déjà le maximum sur ce cas.

- Récupérer `run.json` et l’état de session du run Arcbench, ou relancer le même cas en
  local, puis décomposer : nombre de requêtes, tokens d’entrée, de sortie et en cache,
  temps passé en attente du modèle, en `npm install`, en build, en tests d’acceptation,
  nombre de tours de vérification et de réparations.
- Constituer un jeu de 5 à 10 cas d’exigences différents. Sans lui, une amélioration du
  taux de réussite est invisible et une régression aussi.
- Répéter chaque variante au moins deux fois : le modèle n’est pas déterministe.

`scripts/evaluate.py` et `benchmarks/PROTOCOL.md` font déjà ces comparaisons appariées ;
il manque les runs.

**État : outillage implémenté le 16 novembre 2026 ; aucun run réel lancé.**

- **Décomposition d’un run** : le moteur mesure le temps d’attente du modèle, le temps
  de chaque outil et celui de chaque étape de vérification (intégrité, installation du
  lanceur de tests, dépendances, build, démarrage, génération de tests, acceptation,
  visuel). `run.json` contient ces durées (`budget.timing`), les tokens d’entrée, de
  sortie et en cache, et la liste des tours de vérification avec leur durée.
- **Lecture** : `uv run python scripts/analyze_run.py DOSSIER_OU_RUN.JSON [...]` affiche
  la décomposition d’un run, et un tableau comparatif quand plusieurs sont donnés.
- **Sur Arcbench** : `main.py` écrit en fin de run une ligne `Run breakdown: ...` sur
  la sortie d’erreur, visible dans le journal du runner même si `run.json` n’est pas
  récupérable.
- **Run 1.0** : il a été produit avant ces mesures. S’il reste un `run.json` et son
  dossier d’état, `analyze_run.py` reconstruit le temps du modèle et des outils à partir
  de `events.jsonl` ; le détail de la vérification reste inconnu. Sinon, il faut
  relancer le cas.
- **Jeu de cas** : il existait déjà, contrairement à ce qu’indiquait la première version
  de ce document : 6 cas dans `benchmarks/cases` (4 de développement, 2 de validation)
  plus `input`, soit 7. `evaluate.py --cases benchmarks/cases input` les prend tous.
  Limite : les 6 cas de `benchmarks/cases` sont très courts (1 ou 2 scénarios, ni image
  ni test fourni) ; leur réussite locale repose sur des tests générés par l’hôte. Ils
  détectent une régression grossière, pas une différence fine de qualité. Seuls des cas
  Arcbench supplémentaires, avec leurs tests, combleraient ce manque.
- **Répétitions** : `evaluate.py` fait 2 répétitions par défaut, et le rapport répond
  `insufficient_evidence` en dessous de 2 répétitions par cas ou de 5 cas
  (`min_repeats`, `min_cases` dans `benchmarks/criteria.json`).

Reste à faire, avec votre accord car cela consomme la clé : les runs eux-mêmes.

## 1. Regrouper les actions

**Constat.** Chaque requête renvoie toute la conversation au modèle. Le coût en tokens
d’entrée croît donc avec le nombre de requêtes multiplié par la taille du contexte, et
chaque requête ajoute son temps de réponse. Le profil autorise 16 appels d’outils par
réponse, mais rien n’incite le modèle à en émettre plusieurs, et la boucle les exécute
un par un (`runtime/loop.py`).

**Propositions.**

- Ajouter à `workflow.md` une consigne explicite : lire en un seul message tous les
  fichiers nécessaires, écrire en un seul message tous les fichiers indépendants.
- Ajouter un outil d’écriture groupée (plusieurs fichiers en un appel) et une lecture
  groupée (plusieurs fichiers ou plages en un appel).
- Exécuter en parallèle les appels en lecture seule d’une même réponse (lectures,
  recherches, `http_request`, `database_query`) ; garder l’ordre pour les écritures et
  les commandes.
- Fusionner les enchaînements fréquents en un appel : installer puis construire,
  démarrer puis attendre la réponse HTTP.

**Gain.** C’est le levier le plus direct sur les deux axes : diviser le nombre de
requêtes réduit en proportion le temps d’attente du modèle et les tokens d’entrée
renvoyés. C’est aussi ce que désigne le « traitement par lots » de la demande, sans
le risque de la proposition 8.

**État : implémenté le 16 novembre 2026, effet non mesuré.**

- `workflow.md` demande d’émettre ensemble tous les appels indépendants d’une étape.
- `read_files` lit jusqu’à 8 fichiers ou plages par appel ; chaque fichier est tronqué
  séparément et une entrée illisible n’empêche pas les autres. `write_files` écrit
  jusqu’à 30 fichiers par appel, et rien n’est écrit si un seul chemin est interdit.
- Les appels en lecture seule consécutifs d’une même réponse s’exécutent en parallèle
  (`runtime/loop.py`) : lectures, recherches, exigences, `database_query`, `view_image`,
  journaux et `http_request` en GET. Tout appel à effet s’exécute seul, dans l’ordre
  donné par le modèle, et les résultats sont toujours rendus dans l’ordre des appels.
- `verify_application` installe les dépendances si les manifestes ont changé, et
  `kind: all` enchaîne typage, build et tests backend jusqu’au premier échec.
  `process_start` avec `probe_path` démarre, attend, puis renvoie la première réponse HTTP.

Le gain réel dépend de ce que le modèle fait de ces consignes : à mesurer par un run
comparé à la version 1.0 (nombre de requêtes, tokens d’entrée, durée). Les schémas des
deux nouveaux outils ajoutent quelques centaines de tokens à chaque requête.

## 2. Alléger le contexte renvoyé à chaque requête

**Constat.** La compaction ne se déclenche qu’à 80 % de 400 Ko (`max_context_bytes`,
`compact_ratio`), soit de l’ordre de 80 000 tokens. Jusque-là, chaque observation reste
dans la conversation, dans la limite de 12 000 caractères par résultat d’outil
(`observation_chars`). Un fichier lu puis réécrit, ou un journal de build réussi,
continue d’être facturé à chaque requête suivante.

**Propositions.**

- Remplacer les observations périmées par une ligne : lecture d’un fichier modifié
  depuis, journal d’une commande réussie, sortie d’un build suivi d’un autre build.
- Filtrer les journaux à la source : ne garder que les erreurs et leur contexte pour
  `npm`, `tsc` et le build, au lieu de la fin brute de la sortie.
- Répondre « inchangé depuis la lecture précédente » à une relecture identique.
- Abaisser `observation_chars` et le seuil de compaction, après mesure.
- Vérifier que le fournisseur applique un cache de préfixe (le champ `cached_tokens`
  est déjà relevé dans l’usage) et, si oui, garder le début de la conversation stable :
  instructions et schémas d’outils identiques, historique modifié le plus tard possible.

**Arbitrage.** Élaguer l’historique invalide le cache de préfixe pour la suite. Si les
tokens en cache sont facturés beaucoup moins cher, il vaut mieux élaguer rarement et
par gros blocs ; sinon, élaguer tôt. La mesure de la proposition 0 tranche.

**État : implémenté en partie le 16 novembre 2026, effet non mesuré.**

- **Observations périmées** (`runtime/context.py`, `prune`) : sont remplacées par une
  ligne la lecture d’un fichier entièrement réécrit ensuite ou relu ensuite, le résultat
  d’un contrôle, d’une commande, d’une recherche ou d’une requête refait à l’identique
  plus tard, et les observations de page antérieures aux deux dernières. Le texte exact
  reste récupérable par `read_artifact`. Une lecture suivie d’une modification partielle
  (`edit_file`, `apply_patch`) est conservée : l’agent en a encore besoin pour continuer.
- **Arbitrage avec le cache** : rien n’est modifié tant qu’un bloc de 24 Ko
  (`loop.prune_min_bytes`, 0 pour désactiver) ne peut pas être récupéré d’un coup.
- **Journaux filtrés à la source** : `verify_application` renvoie les lignes d’erreur et
  leur contexte, premières erreurs d’abord, au lieu de la fin brute. `run_command` et
  `install_dependencies` font de même pour `npm`, `npx`, `tsc`, `vite` et équivalents :
  fin de sortie si la commande réussit, erreurs si elle échoue. La sortie des autres
  commandes est inchangée.
- **Relecture identique** : le mécanisme existait déjà pour `read_file`. Correction
  associée : après une compaction, une relecture renvoie de nouveau le texte, au lieu de
  « inchangé » pour un contenu qui n’est plus dans la conversation.
- **Cache de préfixe** : `run.json` donne maintenant les tokens d’entrée, de sortie et
  en cache, et leur rapport (`budget.reported_tokens.cached_input_ratio`). Le début de
  la conversation et les schémas d’outils sont identiques d’une requête à l’autre.

Non fait, faute de mesure : `observation_chars` et le seuil de compaction sont inchangés.
Les arguments des appels d’écriture (le contenu des fichiers écrits) restent dans
l’historique : les remplacer par un résumé risquerait que le modèle imite ce résumé
dans ses écritures suivantes.

Le premier run donnera `cached_input_ratio` : s’il est élevé, relever `prune_min_bytes` ;
s’il est nul, l’abaisser.

## 3. Squelette plus complet et dépendances pré-résolues

**Constat.** Le squelette (`shared/project/templates`) fournit la structure React,
Express et SQLite. Tout le reste est écrit par le modèle, token par token, puis
installé et construit dans le run.

**Propositions.**

- Fournir dans le squelette les briques qui reviennent dans presque toute application :
  session et authentification, accès SQLite avec migrations et données de départ,
  gestion d’erreurs HTTP uniforme, client d’API typé côté frontend, composants de
  formulaire et de mise en page, routeur.
- Livrer un `package-lock.json` pour que l’installation passe par `npm ci`, et
  réutiliser le cache npm entre l’installation de l’agent et la vérification.
- Documenter ces briques en quelques lignes dans les instructions, pour que l’agent les
  utilise au lieu de les réécrire.

**Gain.** Moins de tokens de sortie, qui sont les plus chers et les plus lents à
produire, moins de temps d’installation, et moins d’erreurs sur des parties génériques
déjà testées. **Risque :** un squelette trop marqué gêne une exigence qui s’en écarte ;
les briques doivent rester remplaçables.

**État : implémenté le 16 novembre 2026, effet non mesuré.**

- Briques dans le squelette : `backend/src/lib/http.ts` (erreurs HTTP uniformes, validation
  des champs), `password.ts` (même format que les comptes créés par les données de
  départ), `session.ts` (sessions en base derrière un cookie HttpOnly), et côté frontend
  `api.ts` (client typé, `useResource` sans valeur périmée), `router.tsx` (liens réels,
  routes rechargeables), `form.tsx` (champs dont le nom accessible est exactement le
  libellé, une seule alerte par formulaire), `layout.tsx`. Aucune nouvelle dépendance.
- `BUILDING_BLOCKS.md` décrit ces briques ; son contenu est donné dans le premier message,
  ce qui évite une requête de lecture. `workflow.md` demande de les utiliser.
- `package-lock.json` (281 paquets, binaires Linux et Windows) : installation par `npm ci`.
  Si l’agent ajoute une dépendance, l’installation repasse par `npm install`.
- Vérifié sur une application d’essai sous Linux : `npm ci`, typage, build, 4 tests d’API
  (connexion d’un compte de départ, session reconnue ou non, inscription, erreurs) et un
  parcours dans un vrai navigateur (inscription refusée puis acceptée, session conservée
  au rechargement, déconnexion, routes).

Voir aussi `RECHERCHE_ACCELERATION_AGENT.md` pour les corrections faites après le run
inachevé du 16 novembre (compaction, masquage, commandes bloquées, temps de travail).

## 4. Vérification hôte plus courte

**Constat.** Une application correcte du premier coup est vérifiée deux fois : un tour
incrémental, puis un tour depuis un état propre qui refait le build, le démarrage et
toute la suite d’acceptation (`verification/driver.py`). Playwright tourne avec un seul
worker (`verification/acceptance.py`). Les tests générés par l’hôte demandent des
requêtes au modèle au moment de la vérification.

**Propositions.**

- Quand aucune vérification n’a encore eu lieu, faire directement le tour propre : le
  tour incrémental n’apporte rien dans ce cas.
- Lancer les fichiers de tests sur plusieurs workers, chacun avec sa base de données,
  si les tests sont indépendants entre fichiers.
- Générer les tests d’acceptation manquants pendant que l’agent code, et non après sa
  proposition de fin : ils ne dépendent que des exigences.
- Lancer la comparaison visuelle en parallèle des tests fonctionnels.
- Réduire les attentes fixes (démarrage, délais par test) aux valeurs observées.

**Gain.** Du temps, sans effet sur les tokens. La garantie actuelle est conservée : le
succès vient toujours d’un tour propre.

## 5. Contrat d’interface extrait des tests fournis

**Constat.** Les tests fournis dans `INPUT/tests` supposent des routes, des libellés,
des sélecteurs et des comptes de départ précis. Aujourd’hui l’agent ne voit jamais leur
source : il découvre ces conventions par les échecs de vérification, un tour de
réparation à la fois. Chaque tour coûte un build, une suite de tests et plusieurs
requêtes.

**Proposition.** Faire extraire par l’hôte, sans appel au modèle, les conventions
d’interface des tests fournis (URL visitées, sélecteurs et libellés recherchés, données
de départ attendues) et les donner à l’agent au début, sans les assertions.

**Gain.** Fort sur le taux de réussite si les tests cachés d’Arcbench suivent les mêmes
conventions que les tests fournis, et moins de tours de réparation.

**À trancher.** C’est un changement de principe : le moteur isole aujourd’hui les tests
de l’agent pour qu’il implémente l’exigence et non le test. Donner les conventions sans
les assertions limite ce risque sans l’annuler. À vérifier aussi dans le règlement
d’Arcbench.

## 6. Contrôles rapides avant la proposition de fin

**Constat.** L’agent peut proposer la fin sans avoir lancé le typage ni le build.
L’erreur n’apparaît alors qu’au tour de vérification, le plus coûteux.

**Propositions.**

- À la proposition de fin, lancer d’office le typage et les tests backend (quelques
  secondes) et renvoyer l’échec tout de suite, avant tout tour complet.
- Refuser une proposition tant que des exigences ne sont déclarées couvertes par aucun
  fichier, à partir du registre de couverture existant, en listant leurs identifiants.

**Gain.** Moins de tours complets, donc du temps et des tokens, et moins d’oublis
d’exigences sur des cas plus grands que celui du run.

## 7. Carte du code et recherche ciblée (« RAG » léger)

**Constat.** L’application générée tient en quelques dizaines de fichiers. Un index par
embeddings y coûterait plus qu’il ne rapporte. Ce qui consomme, ce sont les lectures
complètes de fichiers pour retrouver une signature ou une route.

**Propositions.**

- Tenir à jour côté hôte une carte compacte : fichiers, exports, routes HTTP, tables et
  colonnes, composants. La fournir à l’agent après chaque compaction et à la demande.
- Activer `find_symbol`, qui existe déjà comme variante (`variant-symbols.yaml`), et
  mesurer son effet.
- Relier exigences et fichiers : le registre d’interfaces (`interface_write`) permet de
  répondre à « quels fichiers réalisent REQ-3 » sans recherche.
- Pour de grands documents d’exigences seulement : recherche lexicale par identifiant
  et mots-clés dans le catalogue, plutôt que la lecture intégrale.

**Gain.** Moyen sur les tokens, surtout après compaction, quand l’agent relit pour se
resituer. Faible sur ce cas précis, plus net sur de grandes applications.

## 8. Sous-agents parallèles pour les parties indépendantes

**Proposition.** Une fois le schéma de données et le contrat d’API fixés, confier les
pages ou fonctionnalités indépendantes à des sessions parallèles, chacune avec un
contexte réduit, puis intégrer et vérifier dans la session principale.

**Gain.** Potentiellement le plus fort sur la durée. Sur les tokens, le signe est
incertain : chaque sous-agent a un contexte court, mais relit le contrat et le
squelette.

**Risques.** Conflits d’écriture, incohérences entre parties, perte de la vue
d’ensemble qui a justifié l’abandon du pipeline à passes. Le taux de réussite peut
baisser. À n’essayer qu’après les propositions 1 à 4, qui prennent une grande partie du
même gain sans ce risque, et seulement si la durée reste le problème.

## 9. Raisonnement adaptatif et routage de modèles

- Garder le raisonnement `low` pour l’écriture courante ; le relever après deux échecs
  de vérification de même empreinte, moment où l’agent tourne en rond.
- Utiliser un modèle moins cher pour les tâches annexes de l’hôte : génération et revue
  des tests d’acceptation, revue visuelle.

**Gain.** Meilleure réussite sur les cas difficiles pour un surcoût limité aux moments
utiles ; économie sur les requêtes annexes. **Risque :** dépend des modèles disponibles
sur l’endpoint Arcbench ; à comparer à modèle constant d’abord.

## 10. Mémoire des erreurs récurrentes

Relever, sur plusieurs runs, les causes d’échec de vérification qui reviennent, et les
transformer en consignes courtes ou en guides lus à la demande. Le mécanisme existe
(`variant-skills.yaml`), mais son contenu actuel ne vient pas d’erreurs observées.

**Gain.** Dépend entièrement de l’existence d’erreurs récurrentes, donc du jeu de cas
de la proposition 0. **Risque :** des consignes trop nombreuses alourdissent chaque
requête et sur-adaptent l’agent aux cas connus.

## Ordre de mise en œuvre conseillé

1. Proposition 0 : trace du run 1.0 et jeu de cas.
2. Propositions 1, 4 et 6 : peu de code, comportement inchangé, effet sur le temps.
3. Propositions 2 et 3 : effet principal sur les tokens.
4. Décision sur la proposition 5, puis essais comparés des propositions 7, 9 et 10.
5. Proposition 8 seulement si la durée reste trop élevée.

Une proposition n’est retenue que si elle ne fait pas baisser le taux de réussite sur
le jeu de cas, selon les seuils de `benchmarks/criteria.json`.

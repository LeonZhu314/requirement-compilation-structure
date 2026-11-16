# Comparaison du moteur : référence A

La référence du compilateur est figée dans `baseline/compiler.zip`. Le manifeste
contient le commit, les empreintes de l’archive et de ses fichiers, ainsi que celles
de l’archive LingCore étudiée et des rapports historiques conservés. LingCore n’est
pas une dépendance du moteur. L’archive de référence exclut les applications générées,
les secrets et les journaux de conversations. Les rapports de coût conservés ne
permettent pas d’attribuer un score ni une configuration modèle à un run historique.

Les cas de `cases/development/` servent au développement. Ceux de `cases/validation/`
sont réservés aux comparaisons après gel d’une variante ; ils ne sont pas secrets.
Une correction inspirée de leur résultat les transforme en données de développement.
Ces cas locaux complètent l’évaluation officielle, sans remplacer les tests Arcbench.

## Exécution future des comparaisons

1. Extraire la référence dans un dossier distinct ; installer ses dépendances verrouillées.
2. Figer les sources, profil, versions des outils et entrées de la variante candidate.
3. Exécuter les variantes sur les mêmes cas et modèles, avec les mêmes réglages de
   raisonnement, budgets, ressources et conditions de cache. Alterner l’ordre et
   prévoir plusieurs répétitions. Utiliser un workspace et une base neufs par run.
4. Employer les tests externes Arcbench dans leur environnement prévu. Ne pas modifier
   leurs assertions, ne pas les copier dans le contexte du modèle et ne pas utiliser
   de tests cachés pour développer les prompts. Les contrôles locaux ont leur propre résultat.
5. Conserver les sorties applicatives et résultats bruts hors du dépôt, avec leur
   chemin et empreinte dans chaque fiche de run. Conserver aussi les échecs et interruptions.
6. Alimenter `summarize.py` avec les fiches JSONL ; comparer des résultats appariés
   par cas et répétition, jamais uniquement les runs réussis.

Une fiche inclut : `run_id`, `variant`, `case_id`, `repeat`, `source_sha256`,
`input_sha256`, `profile_sha256`, `model`, `reasoning`, `budget`, `environment`,
`status`, `external_passed`, `external_score`, `wall_seconds`, `input_tokens`,
`output_tokens`, `cost`, `artifacts`. Les configurations ne contiennent aucune clé API.
`artifacts` décrit les emplacements et empreintes des sorties/rapports ; les valeurs
inconnues sont `null`. `status` distingue `completed`, `failed`, `interrupted`,
`timed_out`, `budget_exceeded` et `provider_error`. Une fin de conversation seule
ne permet pas de mettre `external_passed` à `true`.

Les tokens en cache sont une partie de l’entrée ; le raisonnement peut être inclus
dans la sortie. Ne pas additionner ces sous-totaux deux fois. Le coût par réussite
inclut les dépenses des échecs et n’est disponible que si tous les coûts sont connus.
Définir la perte maximale de qualité et le gain minimal utile avant le lancement.

## Outillage

`scripts/evaluate.py` applique ce protocole : `plan` affiche les runs prévus, `run --yes`
les exécute (requêtes payantes), `external` rattache un résultat Arcbench à un run et
`report` produit les totaux, les paires et la décision. `variants.json` décrit les
variantes ; la variante `baseline` désigne un dossier où `baseline/compiler.zip` a été
extrait et installé à part. `criteria.json` fixe la perte de qualité maximale et les gains
minimaux : le confirmer (`"confirmed": true`) avant le premier run, ne plus le modifier
ensuite. `status` admet aussi `environment_error` et `verification_missing`.

Le temps jusqu’au premier parcours utilisable est mesuré à la première vérification hôte
où l’application construite a démarré ; le temps de réparation va du premier échec de
vérification à l’acceptation. Ces deux mesures ne sont pas disponibles pour la référence.

## Décomposition d’un run

Chaque `run.json` contient `budget.timing` (secondes d’attente du modèle, d’exécution des
outils, de vérification par étape, et reste non attribué), `budget.reported_tokens`
(entrée, sortie, part en cache) et `verifications` (un enregistrement par tour, avec sa
durée). Les appels d’outils d’une même réponse peuvent se chevaucher : la somme des
secondes par outil peut dépasser le temps total des outils. Une requête au modèle faite
dans un outil ou dans une étape de vérification est comptée dans cet outil ou cette étape.

`scripts/analyze_run.py` affiche cette décomposition pour un ou plusieurs runs.
`main.py` en écrit le résumé sur une ligne (`Run breakdown:`) en fin de run. Les fiches
de `evaluate.py` reprennent `model_seconds`, `tools_seconds`, `verification_seconds`,
`tool_calls` et `failed_verification_rounds`, et le rapport en donne les moyennes par
variante.

`--cases` accepte un dossier de cas (`benchmarks/cases`, ou un de ses sous-dossiers).
Le nombre de répétitions par défaut est 2. `criteria.json` fixe aussi `min_repeats` et
`min_cases` : en dessous, la décision est `insufficient_evidence`.

## État

Le pipeline de référence n’existe plus que dans `baseline/compiler.zip`. `main.py` lance le
nouvel agent. Aucune comparaison réelle n’a été exécutée et aucun score Arcbench n’est
revendiqué pour le nouveau moteur : seuls des essais à modèle simulé ont validé la chaîne.

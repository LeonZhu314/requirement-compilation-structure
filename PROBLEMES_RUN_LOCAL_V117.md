# Problèmes relevés en local, v1.17, Stack Overflow (arc-bench-lite)

Le 17/11/2026, j'ai lancé deux runs locaux sur `arc-bench-lite--stackoverflow` : 27 scénarios et 10 images de référence.

| Run | Dossier | Profil | Fin |
|---|---|---|---|
| 1 | `runs/so-v117` | `arcbench-app` d'origine (délai de requête : 120 s) | `provider_error` après 13 min, application vide |
| 2 | `runs/so-v117b` | copie du profil, délai porté à 600 s pour le diagnostic | arrêté à la main après 1 h 39, au tour de vérification 10 |

## Constat principal

L'application livrée par le run 2 est bonne. Je l'ai sondée à la main avec 11 tests Playwright écrits avec les noms exacts des exigences, dans le style des tests cachés et sur 3 workers en parallèle. **Les 11 passent.** Ils couvrent la connexion et ses erreurs, l'affichage du mot de passe, l'inscription, la recherche anonyme, les contrôles de la page de détail, la publication, la modification, la suppression avec confirmation, les votes et la réputation, l'acceptation d'une réponse et son transfert, les réponses et les commentaires.

Les **9 échecs restants des tests locaux sont tous des défauts des tests générés**, pas de l'application. L'application était écrite au bout de **12 minutes**. Les **87 minutes suivantes** ont été passées à « réparer » une application correcte contre ces tests, avec 19 M de tokens consommés au total.

Les problèmes sont classés par gravité.

---

## A. Tests générés : un oracle faux (cause n° 1 du temps perdu)

### A1. Le générateur ne voit pas les exigences référencées (critique)
- **Constat.** `AcceptanceSuite.task()` et `review()` ne transmettent que l'exigence du test et ses ancêtres, plus `required_locators = catalog.contract_for(requirement)`. Les exigences citées par le scénario sont absentes, alors que les étapes en citent explicitement (`\ref[requirement](REQ-3.3)`, `REQ-2.1`…) et que les `dependencies` les listent.
- **Conséquences mesurées (run 2).**
  - Les 8 fichiers encore en échec créent tous une question par l'interface avec un corps de **40 à 100 caractères**. Or REQ-3.3 exige au moins 220 caractères, ce que le test ne sait pas. L'application refuse donc la publication, à raison (« Question body is required (minimum 220 characters) »), et chaque test échoue ensuite sur « heading/link not found ».
  - Concerne : SCN-REQ-3.4-01, 3.5-01, 3.7-01, 4.1-01, 4.2-01, 4.3-01, 4.3-02, 5.2-01 et 5.3-01. Au tour 9, c'est 9 des 9 échecs.
  - Le formulaire de connexion (REQ-2.1) est deviné à chaque fois : regex `/log ?in|sign ?in/`, `getByLabel(/email/i)`, routes `/login` inventées. De même pour « Ask Question » et « Post Your Question », d'où des boutons « Review your question » inventés et des `.or()` en cascade.
- **Le scénario fournit pourtant l'information.** Le Given dit « the shared UI-created examples supplies a valid body longer than 220 characters », et le corps partagé figure dans les données de départ (`public historical question index`).

### A2. Le relecteur aggrave l'oracle au lieu de le corriger (critique)
Sur 27 relectures dans le run 2, il y a eu 25 « corrigé » et 2 « gardé ». Le relecteur ne voit ni la page, ni le message d'erreur affiché, ni les exigences référencées. Il invente donc une cause et assouplit le test :
- « The requirement never states that the post title is exposed as an ARIA heading ». Faux : REQ-3.2 l'impose, mais le relecteur ne la voit pas.
- « The submit control on the Ask Question form is a link ». Faux : c'est un `<button>`.
- « The root requirement states question titles append the worker-run identifier, so the heading can never equal the raw title ». C'est un contresens : la racine décrit ce que font les *aides des tests cachés*, pas l'application. Le relecteur en a déduit qu'il fallait supprimer `exact: true` sur les titres.
- « The requirement never states that search results persist across a reload », « never mandates an `<img>` », « does not require the post action to land on a page with a title heading » : autant d'assertions retirées.
- **Aucune relecture n'a trouvé la vraie cause** (corps trop court), qui était pourtant visible à l'écran.
- Au run 1, sur l'application vide, il avait aussi « corrigé » 14 fichiers sur 17 en assouplissant les localisateurs de connexion, alors que REQ-2.1 les fixe.

### A3. Les échecs ne disent pas ce que la page affichait
- La relecture reçoit seulement `{'title', 'errors'}`. Le retour à l'agent reçoit `errors[:700]`.
- Ni le contexte d'erreur Playwright (`error-context.md`, l'arbre d'accessibilité au moment de l'échec), ni les `role=alert` visibles, ni l'URL ne sont transmis.
- Ici, une seule ligne « alert : Question body is required (minimum 220 characters) » aurait désigné le test fautif dès le tour 1.

### A4. Un test défectueux finit toujours par être imputé à l'agent
- `MAX_REVIEWS = 2` (v1.17) a bien arrêté les réécritures en boucle. Mais un test toujours faux après 2 relectures reste « échoué » et revient à l'agent comme un défaut de l'application, indéfiniment.
- Il n'existe aucun état « test douteux » qui sortirait le test des échecs bloquants (voir la piste 1 de la partie 4 : deux générateurs, échec seulement s'ils concordent).

### A5. Le rôle « textbox » du mot de passe
- Les exigences écrivent `"Password"(role=textbox)`, alors qu'un `<input type=password>` natif n'a pas de rôle textbox.
- Au run 1 : 15 tests sur `getByLabel('Password', {exact:true})` et 1 sur `getByRole('textbox')`.
- L'application du run 2 expose bien un textbox nommé Password : ma sonde `getByRole('textbox', {name:'Password'})` passe. Le générateur doit pourtant savoir que les tests cachés peuvent viser l'un ou l'autre, et que l'application doit satisfaire les deux.

---

## B. Boucle de réparation sans fin

### B1. Aucune borne, et la stagnation n'est pas détectée
- **Bornes.** Le profil n'en a aucune : `wall_seconds: 0`, `max_verification_rounds: 0`, `max_requests: 0`, `max_reported_tokens: 0`.
- **Détection.** La stagnation exige la même empreinte d'échecs `2 × stagnation_repeats = 6` fois de suite, ou 3 fois de suite entre deux tours du driver. Les empreintes du run 2 sont : 855f · 19e6 · 19e6 · 9836 · 86c7 · 9836 · 9836 · 9836 · deed. Elles alternent d'un ou deux tests (16 → 17 → 16 → 17 → 18 réussis), donc aucune règle ne se déclenche.
- **Durée.** Le run aurait pu tourner des heures ; je l'ai arrêté à 1 h 39.
- **Contrainte du correctif.** Il faut une détection de non-progrès, du type « pas de nouveau scénario réussi depuis N tours », et non un plafond qui bloquerait les gros sites.

### B2. L'agent répare une application correcte
- Une fois l'application écrite (12 min), tout le reste est de la réparation : 9 tours, 26 écritures, 143 lectures de fichiers, 35 `read_artifact`, 47 appels navigateur et 15 `http_request`.
- L'agent n'a heureusement pas assoupli la validation à 220 caractères (vérifié dans `questions.ts` et `QuestionEditor.tsx`). Mais il n'a jamais conclu que le test était faux, faute de pouvoir le lire : les tests de l'hôte lui sont cachés.
- Il manque un moyen de dire « ce test contredit l'exigence X », c'est-à-dire de contester un test avec une preuve.

### B3. Une compaction toutes les 4–5 minutes, et des notes de travail vides
- **Compactions.** Il y en a eu 21 en 100 minutes, à chaque fois de 265–290 ko vers 130–145 ko (`max_context_bytes` 240 000).
- **Notes.** La mémoire de travail après compaction contient `"contracts": [], "established_causes": [], "next_checks": []` : l'agent ne note rien. Il recommence donc son enquête après chaque compaction (relectures des mêmes fichiers et artefacts).
- **Lectures sans écriture.** L'avertissement est apparu 20 fois, jusqu'à **48 étapes de suite** sans écrire (à 74,6 min).
- **Effet sur le contexte.** Le contexte moyen par requête est d'environ 53 000 tokens. Il est rempli surtout de lectures déjà obsolètes, ce qui rejoint la piste CWL de la partie 4 : évincer d'abord ce qui est déjà inscrit sur disque.

---

## C. Fournisseur et délais (run 1)

### C1. Un délai de 120 s par requête est trop court, et fatal (critique)
- `llm.timeout_seconds: 120` alors que `max_output_tokens: 16384`. À 45–75 tokens/s, une réponse longue demande 4 à 6 minutes.
- Au run 1, la 4ᵉ requête principale (l'agent écrit une grosse partie de l'application) a expiré 3 fois de 120 s (362 s), ce qui donne `provider_error` à la 6ᵉ minute, après 6 appels d'outils.
- Le run 2 avec 600 s n'a eu que 6 nouvelles tentatives au total, et aucune expiration fatale.

### C2. Une erreur du fournisseur termine le run
- `provider_error` met fin au run au lieu de reprendre avec des étapes plus petites, comme le fait déjà `CONTINUE['incomplete']`.

### C3. Après l'erreur, l'hôte vérifie quand même le gabarit vide
- Le run 1 a perdu 7 minutes et 34 requêtes (17 générations, 17 relectures) à générer et relire des tests contre une application vide.
- La relecture contre une application non implémentée corrompt en plus l'oracle (voir A2).

---

## D. Temps et coût (run 2, arrêté à 99 min)

| Poste | Valeur |
|---|---|
| Requêtes | 413, dont 358 de l'agent, 17 de génération, 28 de relecture et 10 de description d'images |
| Tokens | 19,1 M en entrée (90 % en cache), 346 k en sortie, dont 266 k de raisonnement |
| Temps modèle de l'agent | 71 min |
| Temps des outils | 27 min |
| Préchauffage | 40 s |
| Écriture complète de l'application | 12 min (de 0 à 12,4 min, typecheck vert) |
| Tour 1 (propre) | 9 min, dont 5,7 min de génération des 27 tests et 3,2 min de relecture de 17 fichiers |
| Tour 2 | 4 min 20 (relecture de 11 fichiers) |
| Tours 3 à 9 | environ 1 min chacun (le plafond `MAX_REVIEWS` fonctionne) |

### D1. La génération des tests est séquentielle et lente
27 scénarios demandent 5,7 min, plus 3,2 min de relecture au premier tour, alors que l'application est déjà prête.

### D2. Une requête d'agent coûte beaucoup
358 requêtes à environ 53 000 tokens de contexte en moyenne : le coût vient du volume de lectures (voir B3), pas des écritures.

---

## E. Ce qui fonctionne (à ne pas casser)
- **Écriture.** L'agent écrit tôt et vite : l'application complète en 12 min, ce qui confirme la correction des boucles de lecture de la v1.16.
- **Livraison.** Le premier tour propre a réussi : build et démarrage verts. `deploy.sh` (`npm install`, `npm run build`, `npm run start`) fonctionne depuis un dossier vierge (vérifié à la main : install en 15 s, build vert).
- **Données de départ.** Les 11 comptes, les 3 tags et les 5 questions historiques sont tous présents, et l'heure fixe est respectée.
- **Contrôles nommés.** Les régions et contrôles portent les noms exacts : `Log in`/`Sign up` (region), `Question post`, `Answers`, `Answer by …`, `Comment …`, `Confirm deletion` (dialog), `Score`/`Asked`/`Modified`/`View count`/`Answer count` (status), `Up vote`/`Accept answer`/`Accepted answer` avec `aria-pressed`.
- **v1.17.** La réutilisation du rapport sur une révision inchangée a servi deux fois (40,8 et 42,1 min, sans nouvelle exécution). Le premier tour est propre. Le plafond de relectures a ramené un tour d'environ 6 min à environ 1 min.

## F. Non vérifié (risques restants pour les tests cachés)
Ma sonde n'a pas couvert :
- les suggestions de tags et l'aperçu Markdown (REQ-3.3) ;
- les messages exacts à 14 et à 219 caractères (SCN-REQ-3.3-02/03) ;
- les erreurs d'inscription (e-mail déjà utilisé, mot de passe court) ;
- le bouton « Forgot password? » une fois la connexion faite ;
- la cohérence entre la liste et le détail (tags, score, nombre de réponses) ;
- l'interdiction des commentaires anonymes (REQ-5.1).

---

## Corrections apportées (v1.18, `outputs/agentnewv1.18.zip`)

Toutes ces corrections sont génériques et n'imposent aucun plafond qui gênerait un site plus grand. Les 180 tests unitaires passent, dont 10 nouveaux (`tests/test_oracle_and_progress.py`). **Effet non mesuré sur un run réel.**

| Problème | Correction |
|---|---|
| A1 | `RequirementCatalog.referenced` suit `dependencies` et les `\ref[requirement]` des étapes, de façon transitive et bornée à 10 exigences. Le générateur et le relecteur reçoivent `referenced_requirements` (texte et localisateurs exacts). Sur Stack Overflow, REQ-4.2 et 5.3 reçoivent maintenant REQ-3.3 (au moins 220 caractères) et REQ-2.1, pour au plus 8 ko par requête. Le générateur a pour consigne de respecter leurs règles en saisissant des données, et de ne pas prendre les descriptions de l'environnement de test (suffixes de titres) pour un comportement de l'application. |
| A2 | Le relecteur reçoit la page au moment de l'échec, les exigences référencées et les localisateurs exigés. Il doit corriger la cause, pas assouplir. Une correction qui retire des `expect(` ou des `exact: true` est refusée (`weakened`). Au premier tour, si aucun test ne passe, aucune relecture n'a lieu. |
| A3 | `failure_pages` lit `error-context.md` de Playwright : l'instantané d'accessibilité, sans le source du test. Les alertes de la page vont dans le retour à l'agent (« The page showed: … »), dans le journal stderr et dans la mémoire de travail. Vérifié avec le vrai Playwright sur un test du run 2 : l'alerte « Question body is required (minimum 220 characters) » remonte. |
| A4 | Un fichier généré relu 2 fois, jugé faux par sa dernière relecture et toujours en échec devient `disputed`. Il est écarté et ne compte plus contre l'application : il n'est ni réussi ni une omission, et il est signalé à l'agent. |
| A5 | La consigne erronée « un champ mot de passe n'a pas le rôle textbox » est retirée. Playwright lui donne ce rôle, ce qui est vérifié sur l'application du run 2. |
| B1 | Arrêt quand le nombre de tests réussis n'a pas atteint de nouveau maximum depuis `stagnation_repeats` tours (3), aussi bien dans le driver que dans `run_acceptance_tests`. Ce n'est pas un plafond : chaque test nouvellement réussi relance le compte. |
| B2 | `run_acceptance_tests` accepte `disputes: [{scenario, reason}]`. Le test contesté est relu avec l'argument de l'agent, que le relecteur juge sur pièces (une relecture supplémentaire par fichier). Un test corrigé est réexécuté même si les sources n'ont pas changé. Les consignes (`workflow.md`, outil, retour de vérification) l'indiquent. |
| B3 | Le raisonnement de l'agent est raccourci au-delà des 3 derniers échanges : sur le run 2, le contexte de travail passe de 164 ko à 110 ko. La compaction garde 55 % de l'espace de travail au-dessus de la tâche, au lieu de 55 % du total, ce qui ne laissait qu'environ 15 ko de travail récent. La mémoire de travail reçoit un `host_journal` : carte du code (fichiers, exports, tables, routes) et historique des vérifications. Seul le dernier retour de vérification reste dans la conversation. L'agent est invité à noter les causes qu'il établit (`note_write`). |
| C1 | `llm.timeout_seconds` : 600. |
| C2 | Après un `provider_error`, le travail reprend une fois avec la consigne de procéder par petites étapes. |
| C3 | Si l'agent n'a écrit aucun fichier et que son tour ne s'est pas terminé par une proposition, l'hôte ne lance ni vérification, ni génération, ni relecture. |
| D1 | Génération des tests : 8 requêtes en parallèle au lieu de 4. |
| D2 | Couvert par B3 : moins d'octets par requête et moins de compactions. |

À faire : un run local de la v1.18 sur ce même site, puis sur un autre, avant de soumettre ; la sonde manuelle ci-dessous permet de comparer.

## Fichiers utiles
- **Run 2 :**
  - `runs/so-v117b/stderr.log` et `runs/so-v117b/.agent-state/23ce4ee2efa44108b25a6677df240c62/events.jsonl` ;
  - `session.json` (rapports de vérification) ;
  - `artifacts/5605765f….json` (échecs du tour 9).
- **Tests générés et relectures :** `runs/so-v117b/.agent-state/_tooling/playwright-1.64.1/sessions/23ce4ee2…/generated/` et `manifest.json`.
- **Sonde manuelle (11 tests) :** `runs/so-v117b/.agent-state/_tooling/playwright-1.64.1/sessions/probe/probe.spec.ts` et `probe2.spec.ts`. Lancement : `ACCEPTANCE_BASE_URL=http://localhost:3456 ../../node_modules/.bin/playwright test -c playwright.config.cjs` depuis ce dossier, l'application étant démarrée.
- **Run 1 :** `runs/so-v117/.agent-state/18ecd686766c43dcb2ff9558b66d44a1/` (erreur du fournisseur, relectures sur l'application vide).

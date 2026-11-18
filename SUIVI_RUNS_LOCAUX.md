# Suivi des runs locaux

Journal des runs locaux de l'agent : version, site, résultats, problèmes observés et corrections. Les runs Arcbench ne sont lancés qu'une fois les résultats locaux probants.

Mesure de référence de l'application livrée : la sonde manuelle de 11 tests Playwright écrits avec les noms exacts des exigences (style des tests cachés), dans `runs/so-v117b/.agent-state/_tooling/playwright-1.64.1/sessions/probe/`.

## Historique

| Date | Version | Site | Durée | Tokens | Tests locaux | Sonde | Fin |
|---|---|---|---|---|---|---|---|
| 17/11 | v1.17 (délai 120 s) | Stack Overflow | 13 min | — | 0/27 | — | `provider_error`, application vide |
| 17/11 | v1.17 (délai 600 s) | Stack Overflow | 99 min (arrêt manuel) | 19,1 M entrée / 0,35 M sortie | 18/27 | 11/11 | boucle de réparation sur des tests faux |
| 17/11 | v1.19 | BookStack lite | 29 min 54 s | 2,3 M entrée (87 % en cache) / 0,12 M sortie | 12/12 | 5/6 (placeholder manquant) | **acceptée** (tour 4, état propre) |
| 17/11 | v1.19 | Stack Overflow, **sur Arcbench** (lancé par l'utilisateur) | 33 min 17 s | 3,9 M (4,56 CNY) | 26/27 + 1 écarté | — | **10/182 aux tests cachés** (≈ 10/28 de ce site) |
| 17/11 | v1.18 | Stack Overflow | 54 min 48 s | 10,0 M entrée (89 % en cache) / 0,40 M sortie | 23/27 + 4 écartés | 11/11, et sonde 3 : 2/6 | **acceptée** (tour 7, état propre) |

Détail des runs v1.17 : `PROBLEMES_RUN_LOCAL_V117.md`.

## Run v1.18, Stack Overflow (17/11/2026)

- Dossier : `runs/so-v118` ; profil `profiles/arcbench-app/config.yaml` sans modification ; même entrée que les runs v1.17.
- Commande : `uv run python main.py ../runs/so-v118/input --profile profiles/arcbench-app/config.yaml --output-dir ../runs/so-v118/app`.

### Déroulement

- **1ʳᵉ compaction, après 9 appels d'outils :** de 266 ko à 130 ko. Une seule réponse `write_files` portait **78 ko de raisonnement** (`reasoning_content`) et 9 ko de fichiers. Ce lot fait partie des 3 derniers, dont le raisonnement reste entier. Comme il dépassait à lui seul la cible de la compaction, seuls les 2 lots suivants (13 ko) ont été gardés.
  → **Problème P1 :** la compaction doit aussi raccourcir le raisonnement des lots qu'elle garde (sauf le dernier) avant de mesurer leur taille. Un raisonnement de 78 ko est en plus renvoyé intégralement dans les 2 requêtes suivantes.
  → **Corrigé (v1.19) :** `compact()` raccourcit le raisonnement de tous les lots gardés sauf le plus récent avant de les mesurer ; test `test_compaction_keeps_more_recent_work_by_shortening_older_reasoning`.
- **Compactions 2 à 4 :** de 270 ko à environ 195 ko. La nouvelle cible garde environ 80 ko de travail récent au lieu d'environ 15 ko.
- **Élagage :** 3 passes à 10 min (environ 30 ko chacune). Aucune erreur du fournisseur : l'API accepte le raisonnement raccourci.
- **15,0 min, tour 1 (état propre) :** build et démarrage OK. La génération des 27 tests prend **2,4 min** (5,7 min en v1.17 ; 8 requêtes en parallèle). Les 16 fichiers en échec sont relus. Le tour dure 4 min 41.
- **Résultat du tour 1 :** **11 réussis, 16 en échec**.
  - **9 échecs** montrent une page réduite au JSON brut `{"error":"Invalid request"}` après un rechargement ou une visite directe d'une page client (`/questions`, détail, éditeur).
  - **Problème P0 (gabarit, générique, critique en local) :** le serveur du gabarit sert les routes client avec `response.sendFile(\`${frontend}/index.html\`)`. Avec un chemin absolu, `send` répond 404 dès qu'un dossier du chemin commence par un point. En vérification locale, l'application tourne dans `.agent-state/<session>/execution` : toutes les routes client rechargées échouent, et `apiErrors` transforme ce 404 en `Invalid request`. Je l'ai reproduit avec Node : `sendFile(absolu)` donne 404, `sendFile('index.html', { root })` donne la page. Sur Arcbench (`/workspace/template`), le défaut n'apparaît probablement pas ; en local, il fausse tous les tests de rechargement. Au run v1.17, l'agent l'avait corrigé lui-même après enquête.
  → **Corrigé (v1.19) :** `templates/backend/src/app.ts` utilise `sendFile("index.html", { root: frontend })`.
  - **Les relectures voient enfin la page.** 3 sur 16 ont correctement accusé l'application (KEEP, « the page is the application's own `{"error":"Invalid request"}` »). Mais **2 relectures ont retiré le `reload()` du test** en accusant le test.
  → **Problème P2, corrigé (v1.19) :** consigne du relecteur : un rechargement ou une visite directe est un comportement ordinaire, et une erreur après rechargement est un défaut de l'application.
  - **Ces pages ne remontent pas à l'agent** : elles n'ont pas d'alerte, donc l'agent ne lit que « element not found ».
  → **Problème P3, corrigé (v1.19) :** une page de quelques lignes sans bannière ni contenu principal (JSON brut, texte d'erreur) est transmise entière : « whole page: … ».
  - **Le mauvais bloc d'instantané est parfois retenu.** Pour certains tests, c'était celui d'un seul élément (`textbox "Password"`) inclus dans le message d'erreur, et non celui de la page.
  → **Problème P4, corrigé (v1.19) :** on retient le bloc d'instantané le plus grand.
- **Pendant la réparation :** jusqu'à 24 étapes de suite sans écrire. L'agent cherche la cause des « element not found » sans voir la page JSON (P3). Il a fini par trouver le défaut de rechargement.
- **Tour 2 (environ 37 min) :** **23 réussis, 0 en échec, 4 écartés** (`disputed`). L'acceptation passe pour la première fois sur ce site.
  - Vérification des 4 tests écartés dans le code de l'application :
    - **SCN-REQ-1.1-01 :** l'application affiche, pour un visiteur anonyme, un second bouton « Log in » dans le corps de la page d'une question. Le test non restreint au bandeau échoue (plusieurs éléments trouvés), et un test caché le ferait aussi. **Défaut de l'application.**
    - **SCN-REQ-3.2-01 :** l'avatar n'est que du texte (des initiales), sans image. REQ-3.2 exige un avatar. **Défaut de l'application**, que le relecteur a jugé à tort comme un défaut du test.
    - **SCN-REQ-5.3-01 :** « Stack User » et la date sont dans le même paragraphe, et le test cherche « Stack User » en texte exact. Cas ambigu.
    - **SCN-REQ-2.1-06 :** test du bouton Afficher/Masquer le mot de passe ; non tranché.
  → **Problème P5 :** écarter un test sans le montrer à l'agent cache de vrais défauts (2 sur 4 ici).
  → **Corrigé (v1.19) :** quand tout le reste passe, l'agent reçoit **une fois** la liste des tests écartés avec ce qu'ils cherchaient (`disputed_review`), avec la consigne de corriger l'application si l'exigence le demande, aussi bien dans `run_acceptance_tests` que dans le driver avant d'accepter.
  → **Problème P6, corrigé (v1.19, `workflow.md`) :** deux règles génériques. Un élément du contrat d'interface est unique sur sa page. Un élément visuel nommé (avatar, logo, icône) est une image (`<img alt>` ou `role="img"` avec `aria-label`).
- **Tour 3 :** **21 réussis, 2 en échec, 4 écartés.** Les 2 échecs (SCN-REQ-4.2-01 et 3.6-01) attendent une réputation de 110 et lisent 120 : deux tests parallèles votent pour le même auteur. L'exigence racine le prévient (« may include other independent case contributions »). Ces deux tests passaient au tour 2 : ils sont instables.
  → **Problème P7, corrigé (v1.19) :** consigne au générateur, mesurer la variation causée par sa propre action sous forme de borne inférieure sur toute valeur partagée (compteur, score, réputation) ; consigne au relecteur, reconnaître ce cas comme un défaut de l'environnement de test.
- **Tours 4 à 7 :** 23 réussis, 0 en échec, 4 écartés à chaque tour. L'agent a refait un tour de lui-même sur des sources inchangées (tours 4 et 5). Après sa proposition de fin, le driver a relancé un tour incrémental identique (tour 6) avant le tour propre (tour 7, accepté).
  → **Problème P8, corrigé (v1.19) :** un tour réussi sur des sources inchangées n'est pas relancé, ni par `run_acceptance_tests` ni par le driver, qui passe directement au tour propre.
  - Le tour 7 a passé **131 s sur la comparaison visuelle**, en mode `report` : un rapport sans effet sur rien.
  → **Problème P9, corrigé (v1.19) :** `acceptance.visual: "off"` dans le profil. Attention, en YAML, `off` sans guillemets est lu comme `false` : c'est corrigé avec des guillemets.

### Résultat

- **Acceptée** au tour 7 (état propre), code de sortie 0, **54 min 48 s**.
- **Temps :** modèle 1 677 s, outils 1 193 s, vérification 1 000 s (dont acceptance 598 s, génération 141 s, visuel 131 s).
- **Volume :** 226 requêtes, 167 appels d'outils, 10,0 M tokens en entrée (89 % en cache), 0,40 M en sortie (dont 0,27 M de raisonnement).
- **Comparé au run v1.17 à délai 600 s :** 99 min → 55 min, 19,1 M → 10,0 M tokens en entrée, 413 → 226 requêtes. La boucle infinie a disparu.
- **Sonde manuelle sur l'application livrée** (même sonde que pour v1.17) : **11/11**.
- **Sonde 3**, nouvelle (`probe3.spec.ts`), qui teste ce que les sondes précédentes ne couvraient pas :

  | Test | Résultat | Commentaire |
  |---|---|---|
  | Rechargement et visite directe des routes client | OK | |
  | REQ-3.3 : aperçu Markdown, compteur, suggestions, messages exacts à 14 et 219 caractères et sans tag | OK | |
  | Bouton « Log in » unique sur la page d'une question (visiteur anonyme) | **2 trouvés** | défaut de l'application, risque pour les tests cachés |
  | Avatar comme image dans la région « Author » | **absent** | initiales en texte seulement |
  | « Stack User » en texte exact dans la région du commentaire | **absent** | collé à la date dans un même élément ; `toContainText` passe |
  | Inscription refusée | échec de la sonde elle-même | « 8 characters » trouvé deux fois ; à rendre exact |

  Les trois défauts de l'application font l'objet des règles P5 et P6, plus une règle « une information nommée = son propre élément » (`workflow.md`).

### Corrections v1.19 (`outputs/agentnewv1.19.zip`, 183 tests unitaires OK)

| Problème | Correction |
|---|---|
| P0 | Gabarit : `sendFile("index.html", { root: frontend })`, ce qui rend les routes client rechargeables sous n'importe quel chemin. |
| P1 | La compaction raccourcit le raisonnement des lots gardés, sauf le plus récent. |
| P2 | Relecteur : une erreur après rechargement ou visite directe est un défaut de l'application. |
| P3 | Une page de quelques lignes (JSON brut, texte d'erreur) est transmise entière à l'agent. |
| P4 | L'instantané de page retenu est le plus grand bloc. |
| P5 | Les tests écartés sont montrés une fois à l'agent avant la fin (`disputed_review`), dans l'outil comme dans le driver. |
| P6 | `workflow.md` : contrôle du contrat d'interface unique sur sa page ; un avatar, un logo ou une icône est une image ; une information nommée est un élément à part. |
| P7 | Générateur et relecteur : les valeurs partagées entre tests parallèles se vérifient en borne inférieure. |
| P8 | Pas de nouveau tour sur des sources inchangées qui viennent de réussir ; le driver passe directement au tour propre. |
| P9 | Comparaison visuelle coupée (`visual: "off"`). |
| — | Les fichiers écartés ne sont plus annoncés comme « relus » dans le journal. |

## Run v1.19, BookStack lite (17/11/2026)

- Dossier : `runs/bs-v119` ; entrée extraite de `arcbench-arc-bench-lite-requirements.zip` (12 scénarios, 7 images) ; profil inchangé.
- En parallèle, l'utilisateur lance la v1.19 sur Arcbench (Stack Overflow).

### Déroulement

- **0 à 11,6 min :** l'application est écrite. 35 requêtes, aucune compaction, aucune série sans écriture, aucune erreur du fournisseur.
- **Tour 1 (11,6 min, état propre) :** **9 réussis, 3 en échec.** Les 3 échecs (REQ-3.1 et REQ-3.2 : créer une page puis l'ouvrir) affichent sur la page l'alerte « Cannot read properties of undefined (reading 'id') ». C'est un vrai défaut, et l'agent le reçoit directement (A3 fonctionne). Les relectures disent KEEP : l'application est en faute (A2 fonctionne).
- **Tour 2 :** **9 réussis, 0 en échec, 3 écartés.** La page créée n'apparaît toujours pas dans « Page list ».
  → **Problème P10 :** `dispute()` ne regardait que la dernière relecture. Ici, 1ʳᵉ relecture KEEP (l'application est en faute), puis 2ᵉ relecture avec une correction qui affaiblissait le test, refusée. Le test a été écarté alors qu'il signale un vrai défaut.
  → **Corrigé (v1.20) :** un fichier n'est écarté que si **toutes** ses relectures l'ont réellement corrigé. Un KEEP ou une correction refusée le laisse compter. Test `test_a_test_any_review_kept_or_refused_is_never_set_aside`.
  - Avec la v1.19, l'agent reçoit quand même la liste des tests écartés (P5) avant la fin.
- **Tour 3 :** **12 réussis, 0 en échec, 0 écarté.** L'agent a reçu la liste des tests écartés (P5) et a corrigé le vrai défaut (la page créée absente de « Page list »). La correction P5 a servi.
- **Tour 4 (état propre) :** lancé directement, sans tour incrémental intermédiaire (P8 fonctionne). **12/12, acceptée.**

### Résultat

- **Acceptée**, code de sortie 0, **29 min 54 s**.
- **Volume :** 75 requêtes, 59 appels d'outils, 2,3 M tokens en entrée (87 % en cache), 0,12 M en sortie.
- **Temps :** modèle 1 343 s, outils 390 s, vérification 251 s (dont génération 108 s). 4 tours de vérification.
- **Contexte :** aucune compaction, aucune série d'étapes sans écriture.
- **Comparaison** avec les runs Arcbench précédents sur BookStack : v1.13 en 36 min (6/12 cachés), v1.15 lite bloquée plus de 73 min.
- **Sonde manuelle BookStack** (nouvelle, `sessions/probe-bookstack/bookstack.spec.ts`, 6 tests écrits avec les noms exacts des exigences, rechargements compris) : **5/6, puis 6/6 sans la vérification du placeholder**.
  → **Problème P11 :** REQ-3.1 demande que « Page title » et « Write your page content here... » soient « also exposed with those placeholders ». Le second a son placeholder, pas le premier. La consigne de `workflow.md` ne couvrait que les champs décrits par un texte d'aide.
  → **Corrigé (v1.20) :** la consigne est généralisée (tout champ annoncé « exposed with placeholders » reçoit son nom comme placeholder). Le générateur vérifie les placeholders que l'exigence nomme.

## Run v1.19, Stack Overflow, sur Arcbench (lancé par l'utilisateur, 17/11/2026)

- **Score caché :** **10/182** (5,5 %). Le total couvre les 6 sites ; Stack Overflow a environ 28 tests, soit à peu près **10/28**, contre 0/28 en v1.14 et v1.16.
- **Durée :** 33 min 17 s ; 4,56 CNY ; 3,9 M tokens ; 100 requêtes (60 de l'agent).
- **Déroulement :**
  - application écrite en 21 min, avec 10 compactions ;
  - tour 1 : 19 réussis, 8 en échec (« Question not found » sur 4 tests) ;
  - tour 2 : 26 réussis, 1 écarté ;
  - tour 4 (état propre) : accepté.
- **Constat :** l'écart entre le local (26/27) et les tests cachés (≈ 10/28) reste énorme. Arcbench ne donne que le total. Il faut le détail par test pour savoir quels tests cachés échouent.
- **Indices tirés des aides de tests Arcbench fournies** (`input/tests/helpers.ts`, site d'exemple) :
  - les tests cachés vérifient des URL (`toHaveURL(/\/login\/?$/)`, `/\/$/` après la connexion), ce que notre générateur évite volontairement ;
  - ils cherchent du texte exact (`getByText(name, { exact: true })`) ;
  - ils localisent tout par rôle et nom exact.
- **Problème P12 (générique) :** les scénarios nomment des parties de page sans annoter leur rôle (« Click Ask Question **in Question feed** », « Follow Questions **in Main navigation** »). Elles n'entraient pas dans le contrat. Aucune des applications générées n'avait de région « Question feed », alors que tous les tests locaux passaient. Un test caché limité à cette région échoue, ainsi que tout ce qui en dépend (REQ-3.1, REQ-3.3).
  → **Corrigé (v1.21) :** `named_areas` extrait ces noms (deux mots après « in / within / from / on »), sauf les champs (« fill X », « X textbox ») et les noms déjà dans le contrat. L'agent les reçoit dans `named_areas`, avec la consigne de donner à chaque zone un élément enveloppant portant ce nom exact. Le générateur en limite ses localisateurs. Résultat sur les 6 sites : SO `Main navigation, Question feed` ; ctrip `Global navigation, Flight results, Economy fare` ; prestashop `Product list, Shopping cart, Global navigation, Account overview` ; 12306 `Train type, Please confirm` (le second est du bruit sans conséquence) ; BookStack et Keep rien de plus.

### Analyse du `project.zip` téléchargé depuis Arcbench (`runs/arc-v119/`)

L'interface Arcbench (onglet File, bouton « project.zip ») donne le dossier livré **tel qu'il était après les tests cachés**. Il contient :

- **`.arc/runner-events.jsonl`, les étapes du runner :**
  - `deploy.sh` lancé, application joignable en 17 s ;
  - « Test environment ready with **1 workers** » (en local, nous en utilisons 3) ;
  - « Playwright results parsed: **passed=10, failed=17**, score=37.0 ».
  - Il y a donc **27 tests cachés**, un par scénario. Le 10/182 affiché est cumulé sur les 6 sites.
- **`.arc/preflight.json` :** Node v22.12.0, **Playwright 1.57.0** côté runner (1.64 en local).
- **`.arc/traceability/` :** les exigences et scénarios ; `tests.json` et `interfaces.json` sont vides (« No interfaces or tests are linked to this requirement yet » dans l'interface). Le runner indique que la traçabilité doit être écrite « directly by the SDK » ; ce n'est pas nécessaire au score.
- **`requirements/` dans l'espace de travail :** `requirements.yaml`, `requirements.md` et `prerequisites.md` (vide).
- **`backend/data/app.db`, la base de l'application après les tests cachés** (copie gardée dans `runs/arc-v119/app.db.after-hidden-tests`). C'est l'indice le plus utile :
  - 16 sessions : les connexions fonctionnent, une toutes les 11 s environ (1 worker) ;
  - `question_creator` s'est connecté 7 fois, puis `question_editor`, `question_deleter`, `question_upvoter`, `answer_accept_owner` ;
  - **`sqlite_sequence` des questions = 5 : aucune question n'a jamais été créée**, ni gardée ni supprimée. Il n'y a aucun commentaire, aucun vote, aucune révision ;
  - une seule inscription a réussi (`new_stack_user+<suffixe>@example.com`) ;
  - la question « retry » a 44 vues (42 + 2 ouvertures).
- **Conclusion :** tous les tests qui créent une question par l'interface ont échoué entre la connexion et la publication. Ce sont REQ-3.3 (3 scénarios), 3.4, 3.5, 3.7, 4.1, 4.2, 4.3 (2), 5.2 et 5.3, soit 12 scénarios, plus REQ-3.1 (« Question feed exposes Ask Question »).

**Les 3 sondes sur cette application** (démarrée en local) : **15/17**. Créer, répondre, commenter, voter et supprimer fonctionnent en passant par le bouton « Ask Question » sans le limiter à une zone. Les tests cachés passent donc par un autre chemin. Le code confirme lequel : **aucune région « Question feed »** n'existe, alors que le scénario dit « Click Ask Question **in Question feed** ». C'est exactement P12, corrigé en v1.21.

Autres défauts de l'application vus par les sondes :
- l'aperçu Markdown ne rend pas `**gras**` (REQ-3.3 : « Markdown renders live in Preview ») ;
- l'inscription avec un mot de passe de 5 caractères connecte l'utilisateur (REQ-2.2 exige au moins 8 caractères). Le test généré a sans doute vu le texte d'aide « 8 characters » et conclu au rejet sans vérifier que la session n'avait pas été créée.

**Résultats par test** (panneau « Test Results », à droite de la page de la soumission, filtres All / Passed / Not passed, « + » pour le détail). Premières lignes :

| Test caché | Résultat | Durée |
|---|---|---|
| REQ-1.1 Read without an account | ✓ | 0,8 s |
| REQ-2.1 Sign in and retain session | ✗ | 10,0 s |
| REQ-2.1 Reject empty credentials / malformed email / unknown account / wrong password | ✓ | 0,4–0,6 s |
| REQ-2.1 Toggle password visibility | ✓ | 0,5 s |
| REQ-2.2 Register and automatically sign in | ✗ | 10,0 s |
| REQ-2.2 Reject duplicate email / weak password | ✓ | 0,5–0,7 s |

Les échecs durent 10,0 s : c'est la limite d'un test caché, qui a attendu un élément jamais apparu.

**Détail complet**, réponse JSON de l'API Arcbench lue dans les outils du navigateur (onglet Réseau, requête `<run id>?include_step_logs=false&include_t…`, champ `tests`) :
- **Les 17 échecs** donnent tous la même erreur : `Test timeout of 10000ms exceeded`. La limite d'un test caché est de **10 s au total** ; les tests réussis durent 0,4 à 0,8 s.
- **Les 10 tests réussis** sont tous anonymes ou des refus : REQ-1.1 (lecture anonyme), REQ-2.1 (identifiants vides, e-mail mal formé, compte inconnu, mauvais mot de passe, affichage du mot de passe), REQ-2.2 (e-mail déjà pris, mot de passe trop faible), REQ-5.1 (fil de commentaires anonyme), REQ-6.1 (recherche).
- **Les 17 échecs** comprennent toutes les connexions réussies (REQ-2.1 « Sign in and retain session », REQ-2.2 « Register and automatically sign in », puis tous les scénarios authentifiés de REQ-3.2 à REQ-5.3), ainsi que REQ-3.1 (anonyme : « Question feed exposes Ask Question… »).
- La connexion réussit (sessions en base), et le bouton de profil s'appelle bien « Stack User » (`aria-label={user.displayName}`). Mais le scénario de connexion dit « **Question feed appears** ». L'aide de connexion des tests cachés attend donc très probablement la région « Question feed » après chaque connexion, et elle n'existe pas : chaque test authentifié attend jusqu'à la limite. Une action Playwright sans délai propre attend jusqu'à la limite du test, d'où « Test timeout » plutôt qu'un échec d'assertion.
- **Conclusion :** une seule zone absente, « Question feed », explique les 17 échecs. C'est exactement P12, corrigé en v1.21. Il reste deux défauts secondaires, que les tests cachés n'ont pas pu atteindre : le gras de l'aperçu Markdown et le mot de passe court accepté.
- **Pour diagnostiquer les prochains envois :** cette réponse JSON (`tests[].name / status / duration_ms / error`) suffit ; il n'y a pas d'autre détail par test.

**Pour les prochains envois :** télécharger chaque fois le `project.zip`. La base `backend/data/app.db` montre ce que les tests cachés ont réussi à créer, ce qui remplace en partie le détail des tests qu'Arcbench n'affiche pas. Le panneau « Preview · Results » à droite de l'interface est à explorer.

### Version v1.21 (`outputs/agentnewv1.21.zip`, 185 tests unitaires OK)

v1.20 plus P12 (zones nommées). Les exemples tirés de Stack Overflow dans les textes lus par le modèle (`workflow.md`, consignes du générateur, notice des zones nommées) sont remplacés par des exemples neutres, pour ne pas orienter l'agent vers ce site. **Rappel de l'utilisateur :** Stack Overflow n'est qu'un exemple, et toute correction doit valoir pour tous les sites.

**Portée générique des corrections de cette série :**

| Correction | Mécanisme | Vérifié sur |
|---|---|---|
| Exigences référencées (A1) | champs `dependencies` et `\ref[requirement]` du format Arcbench | SO, BookStack (run) |
| Page à l'échec (A3, P3, P4) | `error-context.md` de Playwright | SO, BookStack (runs) |
| Tests écartés, contestation, arrêt sans progrès | relectures et décomptes de l'hôte | SO, BookStack (runs) |
| Gabarit `sendFile` (P0) | serveur du gabarit commun | tous les sites |
| Zones nommées (P12) | expressions « in / within / from X » des scénarios | extraction vérifiée sur les 6 sites |
| Règles `workflow.md` (unicité, image, information séparée, placeholders) | formulations générales | — |

**À faire pour le vérifier :** des runs locaux sur les autres sites (12306, ctrip, keep, prestashop), tous extraits dans `runs/all-sites/`, et des envois Arcbench sur plusieurs sites.

### Envoi Arcbench v1.21, BookStack (18/11/2026)

- **Résultat :** **6/12** (6/182 au total), 12 min 38 s, 1,15 CNY, 1,0 M tokens. Ce sont les mêmes 6 échecs qu'en v1.13.
- Le panneau « Test Results » donne **le code source des tests cachés** en échec. Il est gardé pour le diagnostic dans `runs/arc-bookstack-v121/hidden-tests-failed.md` et n'est jamais donné à l'agent.
- **Causes, lues directement dans les tests :**
  1. `button(page, 'Edit').click()` : « Edit », que l'exigence nomme sans rôle, est attendu comme un **bouton**. L'application en faisait un lien, parce que notre consigne disait « un lien pour ouvrir une page ». Cela suffit à faire échouer les 3 tests sur les livres.
  2. `getByPlaceholder('Page title')` : il faut le placeholder (P11, corrigé en v1.20 ; cet envoi v1.21 en bénéficiait).
  3. `createPage(...)` : l'aide n'est pas montrée, mais « New Page » est sans doute cliqué comme bouton. L'application en faisait un lien, d'où les 3 tests sur les pages.
- **La convention, vérifiée sur deux sites :**
  - **site d'exemple :** « Register link » et « Login link » donnent `link(...)` ; « submit button Next step » et « Logout » donnent `button(...)` ;
  - **BookStack :** « Books »(role=link) donne un lien ; « Edit », « New Page », « Cancel », « Save Book » donnent `button(...)` ;
  - **Stack Overflow :** « Questions » du menu de navigation est un lien (REQ-1.1 passait).
  - Règle : un contrôle n'est un lien que si l'exigence l'appelle ainsi ou s'il fait partie d'un menu de navigation. Tous les autres sont des boutons, même s'ils changent de page.
- **Problème P13, corrigé (v1.22) :** cette règle est appliquée partout :
  - `workflow.md` remplace « a link to open a page, a button to act » ;
  - la notice du contrat d'interface ;
  - le générateur de tests (fini le `.or()` lien/bouton par défaut pour un contrôle sans rôle) ;
  - le relecteur (un test qui cherche un tel contrôle comme bouton a raison).
  
  Test `test_unannotated_controls_are_buttons_for_the_agent_and_the_generated_tests`.

### Envoi Arcbench, Stack Overflow, v1.21 ou v1.22 (18/11/2026)

- **Résultat :** **tests 46,4 %** (37 % en v1.19), « Features » 35,3 %, 40 min 52 s, 4,1 M tokens, 4,56 CNY.
- Code des tests en échec et tableau des aides partagées des tests cachés : `runs/arc-so-v12x/hidden-tests-failed.md` (diagnostic uniquement).
- **Constat :** la région **« Question feed »** reste au cœur des échecs :
  - directement : REQ-3.1, REQ-3.3 (3 tests), REQ-3.5, qui l'attend juste après une suppression ;
  - à travers l'aide `createQuestion`, qui prépare le `Given` « UI-create » : REQ-3.4, 3.5, 3.7, 4.1, 4.2, 4.3 (2), 5.2, 5.3.
  
  Les exigences la placent sur la page d'accueil (« returned homepage… Question feed appears », « returns to the populated homepage ») et sur la liste des questions. Cause à établir sur le `project.zip` de cet envoi : zone absente, mal nommée, ou absente de l'accueil.
- **REQ-3.2** vérifie des détails absents du texte de l'exigence et tirés du produit d'origine :
  - un texte qui commence par « Asked », « Modified » et « **Viewed** » ;
  - le mot « badge » dans la zone « Author » ;
  - « Author » et « Comments » **dans** « Question post ».
- **Problème P14, corrigé (v1.23, `workflow.md`) :**
  - ce qu'une exigence décrit comme partie d'une zone est imbriqué dans l'élément de cette zone ;
  - une zone placée sur plusieurs pages existe sur chacune ;
  - une valeur nommée a aussi une étiquette visible devant elle, formulée comme dans le produit d'origine.

**Analyse du `project.zip` de cet envoi (v1.21, `runs/arc-so-v12x/`) :**
- La v1.21 **a bien créé** `<section aria-label="Question feed">`, sur l'accueil, la liste des questions et la page des tags (P12 fonctionne).
- Mais **« Ask Question » est en dehors de la zone**, dans l'en-tête de la page juste au-dessus. Le test cherche `action(region(page,'Question feed'),'Ask Question')` et ne le trouve pas.
- Dans la base après les tests, les questions 6 à 10 sont des **exemples inventés par l'agent** d'après les captures de référence, pas des créations des tests. Les tests cachés n'ont donc **toujours créé aucune question** : `createQuestion` échoue au même endroit.
- **Problème P15 (générique) :** la consigne d'imbrication restait vague. Les scénarios disent pourtant précisément quel contrôle est dans quelle zone (« Click **Ask Question** in **Question feed** », « **Question feed** exposes **Ask Question** », « Follow **Questions** in **Main navigation** »).
  → **Corrigé (v1.23) :** `contained_controls` (`contract.py`) extrait ces paires, en ne gardant que les zones connues (zones nommées, ou régions, navigations et dialogues du contrat). L'agent reçoit `controls_inside_areas`, avec la consigne de mettre le contrôle *dans* l'élément de la zone sur chaque page où elle apparaît. Le générateur reçoit les mêmes paires sous forme de localisateurs. Résultat sur les 6 sites :
  - SO : Questions→Main navigation, Ask Question→Question feed, Up vote→Answer by Helpful User, Add a comment→Question post ;
  - ctrip : Log in→Global navigation, Cancel order→Payment status, … ;
  - prestashop : Sign in→Global navigation, … ;
  - BookStack et Keep : rien ;
  - 12306 : 2 paires sans grande importance.
  
  Test `test_controls_the_scenarios_use_inside_an_area_are_listed_with_that_area`.

## Envoi Arcbench v1.23, 12306 (18/11/2026) : arrêté à la main après environ 8 h

(D'abord attribué par erreur à Ctrip ; c'était 12306.)

- **Site volumineux :** 49 scénarios, 30 fichiers de tests générés (48 tests), contexte d'environ 230 ko.
- **Application écrite en 18 min.** La génération des tests prend 11 min ; le tour 1 dure 17 min.
- **Tests locaux réussis par tour :**

  | Tour | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
  |---|---|---|---|---|---|---|---|---|---|---|---|
  | Réussis (sur 48) | 6 | 0 | 14 | 22 | build en échec | 17 | 28 | 32 | 34 | **36** | 30 |

- **Une requête au modèle toutes les ~1 min 45**, en continu (le fournisseur répond lentement sur ce contexte). Entre deux tours, l'agent travaille de 25 min à 2 h.
- **Lectures sans écriture :** jusqu'à 96 étapes de suite (environ 1 h).
- **Problème P16 :** l'arrêt sans progrès ne comptait que les **tours** (3 sans nouveau record). Comme l'agent ne lance un tour que toutes les 25 min à 2 h, la règle ne protégeait de rien.
  → **Corrigé (v1.24) :**
  - l'arrêt compte aussi les **requêtes au modèle depuis le dernier record** (`NO_PROGRESS_REQUESTS = 150`, et au moins un tour sans record), dans le driver comme dans `run_acceptance_tests` ;
  - au bout de **48 étapes sans écrire** (`LOOKING_LIMIT`), le tour de l'agent se termine et l'hôte vérifie l'application telle quelle : le retour de vérification remplace la lecture, et ce tour compte dans l'arrêt sans progrès.
  
  Ce ne sont pas des plafonds de taille : chaque nouveau record remet les compteurs à zéro.
- **Échecs locaux récurrents, d'où deux règles génériques en v1.24 (`workflow.md`) :**
  - « Element is not a <select> element » : un choix parmi des options fixes doit être un `<select>` natif (l'aide de test d'exemple d'Arcbench fait `selectOption`) ;
  - « strict mode violation : button '2026-07-21' resolved to 2 elements » : un contrôle cliqué par son nom doit être unique sur la page (calendrier sur deux mois).

## Résultats Arcbench de la v1.23 sur les 6 sites (18/11/2026)

| Site | Score Arcbench | Tests cachés | « Features » | Durée | Tokens | Coût |
|---|---|---|---|---|---|---|
| BookStack | 114,07 | **100 %** | 100 % | 8 min 03 s | 1,29 M | 1,29 CNY |
| Keep | 111,20 | **100 %** | 100 % | 18 min 01 s | 2,09 M | 1,52 CNY |
| PrestaShop | 92,11 | **87,5 %** | 78,9 % | 177 min 01 s | 12,93 M | 6,70 CNY |
| Stack Overflow | 89,19 | **85,7 %** | 82,4 % | 29 min 11 s | 8,06 M | 6,45 CNY |
| Ctrip | 31,10 | 30 % | 18,8 % | 35 min 12 s | 2,42 M | 4,18 CNY |
| 12306 | 0 | — | — | arrêté après ~8 h | — | — |

- BookStack passe de 6/12 (v1.21) à 12/12 : la règle « boutons par défaut » (v1.22) était la cause.
- Stack Overflow passe de 46,4 % à 85,7 % : « Ask Question » est maintenant dans « Question feed » (v1.23).
- Keep, envoyé pour la première fois, atteint 100 %. Les corrections tirées de deux sites valent donc pour les autres.
- **Points faibles :** Ctrip (30 %), 12306 (aucun score, boucle de plusieurs heures, traitée en v1.24), et la durée de PrestaShop (177 min, 12,9 M tokens).
- **À faire :** analyser les tests en échec de Ctrip et de PrestaShop (code des tests, `project.zip`) et le journal du run PrestaShop pour comprendre les 177 min.

### Version v1.24 (`outputs/agentnewv1.24.zip`, 188 tests unitaires OK)

v1.23 plus P16 (arrêt sans progrès compté en requêtes, fin de tour après 48 étapes sans écrire) et les deux règles ci-dessus, issues du run 12306.

### Version v1.23 (`outputs/agentnewv1.23.zip`, 187 tests unitaires OK)

v1.22 plus P14 (imbrication, zones sur plusieurs pages, étiquettes visibles des valeurs) et P15 (contrôles dans leur zone).

### Version v1.22 (`outputs/agentnewv1.22.zip`, 186 tests unitaires OK)

v1.21 plus P13 (contrôles sans rôle = boutons).

### Tests cachés BookStack en échec, envoi Arcbench de la **v1.13** (6/12, donnés par l'utilisateur le 18/11)

La v1.13 précède presque toutes les corrections de cette série (gabarit, exigences référencées, page à l'échec, relectures, zones nommées, placeholders). La cause des échecs « Edit » de la v1.13 ne sera pas recherchée. **Prochaine mesure :** envoi de la v1.21 sur BookStack.

**6 échecs :**
- Save a new book (REQ-2.3-01) ;
- Save metadata changes (REQ-2.4-01) ;
- Cancel metadata changes (REQ-2.4-02) ;
- Publish a page (REQ-3.1-01) ;
- Read selected page (REQ-3.2-01) ;
- Reopen page editor (REQ-3.2-02).

**Réussis :** ouverture de l'espace, liste et ouverture d'un livre (ces tests créent un livre : la création fonctionne), annulation d'une création, suppression et conservation d'un livre.

**Points communs des échecs :**
- les 3 tests de livre utilisent **Edit**, ce qu'aucun test réussi ne fait ;
- les 3 tests de page passent par le formulaire **New Page**, dont l'exigence dit que les champs sont « also exposed with those placeholders ».

**Comparaison avec l'application v1.19 locale :**
- « Edit » et « New Page » sont des liens portant ces noms exacts ;
- les tags sont relus tels quels ;
- la sonde rejoue les 6 parcours avec succès, mais il **manque le placeholder « Page title »** (P11, corrigé en v1.20), ce qui suffit à faire échouer les 3 tests de page si le test caché localise les champs par placeholder.

**Cause des 3 échecs Edit :** non établie. Il faut le `project.zip` et le JSON de cet envoi, ou un nouvel envoi de la v1.21 sur BookStack.

### Version v1.20 (`outputs/agentnewv1.20.zip`, 184 tests unitaires OK)

v1.19 plus P10 (mise à l'écart seulement si toutes les relectures ont corrigé le test) et P11 (placeholders).

### Prochaine étape

Comparer avec le score Arcbench de la v1.19 sur Stack Overflow, puis refaire un run local de Stack Overflow avec les trois sondes.

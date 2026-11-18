# Historique des versions de l'agent (v1.0 → v1.24)

Ce document retrace, version par version :
- ce qui a changé et comment ça fonctionne ;
- pourquoi ce changement a été fait ;
- ce que l'on sait de son effet ;
- **son statut dans la version actuelle (v1.24)** : gardé, modifié (et par quelle version) ou retiré.

Les seuls résultats retenus sont ceux des **runs réels** : envois sur Arcbench (tests cachés) et, pour quelques versions, des runs locaux décrits par leur durée, leur consommation et leur issue.

Les scores des tests générés localement par l'hôte ne sont pas repris : ils se sont révélés peu fiables. Par exemple, la v1.19 obtenait 26/27 en local mais 10/27 sur Arcbench.

**Modèle utilisé partout :** `deepseek-flash`, raisonnement `low`.

**Légende des statuts :** ✅ gardé · 🔁 gardé mais modifié · ❌ retiré ou désactivé.

## Résultats Arcbench

Un score « x/182 » affiché par Arcbench cumule les 6 sites de la compétition. Le score propre au site est donné entre parenthèses quand il est connu.

| Version | Site | Tests cachés | Durée | Coût | Tokens |
|---|---|---|---|---|---|
| v1.0 | site d'exemple | 5/5 | 46 min 03 s | 3,43 CNY | — |
| v1.2 | site d'exemple | inachevé : toujours en auto-test après 60 min | — | — | — |
| v1.3 | site d'exemple | 5/5 | 52 min 18 s | 1,31 CNY | — |
| v1.3 | BookStack | 6/12 | 69 min | 2,52 CNY | — |
| v1.6 | site d'exemple | 5/5 | 29 min 24 s | 1,40 CNY | — |
| v1.7 | BookStack | 6/182 | 68 min | — | — |
| v1.8 | site d'exemple | 5/5 | 20 min 01 s | 1,28 CNY | — |
| v1.8 | BookStack | 2/12 | 33 min | — | — |
| v1.10 (raisonnement `none`) | site d'exemple | 5/5 | 27 min | 2,75 CNY | — |
| v1.13 | site d'exemple | 5/5 | **5 min 15 s** | **0,52 CNY** | — |
| v1.13 | BookStack | 6/12 | 36 min | — | — |
| v1.14 | Stack Overflow | 0/28 | 98 min 46 s | 17,20 CNY | 31,2 M |
| v1.14 | BookStack complet | 0/35 | 59 min 23 s | 10,86 CNY | 16,1 M |
| v1.15 | BookStack lite | aucun score (arrêté à la main) | plus de 100 min | — | — |
| v1.16 | Stack Overflow | 0/182 | 101 min 34 s | 12,93 CNY | 13,9 M |
| v1.19 | Stack Overflow | 10/182 (**10/27**, 37 %) | 33 min 17 s | 4,56 CNY | 3,9 M |
| v1.21 | BookStack | 6/182 (**6/12**) | 12 min 38 s | 1,15 CNY | 1,0 M |
| v1.21 | Stack Overflow | **46,4 %** | 40 min 52 s | 4,56 CNY | 4,1 M |
| v1.23 | **BookStack** | **100 %** (12/12) | 8 min 03 s | 1,29 CNY | 1,3 M |
| v1.23 | **Keep** | **100 %** | 18 min 01 s | 1,52 CNY | 2,1 M |
| v1.23 | **PrestaShop** | **87,5 %** | 177 min 01 s | 6,70 CNY | 12,9 M |
| v1.23 | **Stack Overflow** | **85,7 %** | 29 min 11 s | 6,45 CNY | 8,1 M |
| v1.23 | Ctrip | 30 % | 35 min 12 s | 4,18 CNY | 2,4 M |
| v1.23 | 12306 | aucun score (arrêté à la main après ~8 h) | ~8 h | — | — |

La v1.23 a été envoyée sur les 6 sites de la compétition (scores Arcbench : BookStack 114,07, Keep 111,20, PrestaShop 92,11, Stack Overflow 89,19, Ctrip 31,10, 12306 0). La v1.22 n'a pas été envoyée seule ; ses corrections sont incluses dans la v1.23. La v1.24 n'a pas encore été mesurée.

## Vue d'ensemble de ce qui a été retiré ou remplacé

| Élément | Introduit | Devenu | Pourquoi |
|---|---|---|---|
| Images de référence jointes à la conversation | v1.15 | ❌ retiré en v1.17 (retour aux descriptions textuelles) | demande de l'utilisateur ; gain non démontré, coût en contexte |
| Différences visuelles renvoyées à l'agent avant la fin | v1.15 | ❌ désactivé en v1.17 (`acceptance.visual_feedback: false`) | même raison |
| Comparaison visuelle en fin de run | avant v1.0 | ❌ coupée en v1.19 (`acceptance.visual: "off"`) | 131 s par run pour un rapport sans effet |
| Capture des pages à paramètres (`/books/:id`) | v1.15 | ❌ inactive (ne sert qu'à la comparaison visuelle, coupée) | idem |
| Variante raisonnement `none` | v1.10 | ❌ abandonnée (`low` conservé) | plus lente et plus chère au run de mesure |
| Règle du générateur « un mot de passe n'a pas le rôle textbox » | v1.13 | ❌ remplacée en v1.18 | fausse : Playwright donne ce rôle au champ mot de passe |
| Consigne « un lien pour ouvrir une page, un bouton pour agir » | v1.8 | 🔁 remplacée en v1.22 | les tests cachés attendent un bouton pour tout contrôle non annoncé comme lien |
| `.or()` lien/bouton par défaut dans les tests générés | v1.12 | 🔁 limité en v1.22 aux alternatives annoncées par l'exigence | même raison |
| Relecture : seule la dernière décision comptait pour écarter un test | v1.18 | 🔁 corrigé en v1.20 | un vrai défaut avait été écarté |
| Arrêt sans progrès compté seulement en tours | v1.18 | 🔁 complété en v1.24 (aussi en requêtes) | inefficace sur un gros site (12306) |
| Fallback des routes client du gabarit (`sendFile` avec chemin absolu) | gabarit v1.1 | 🔁 corrigé en v1.19 | page rechargée en 404 sous un dossier commençant par un point |

---

## v1.0 : point de départ

- **Contenu :**
  - un agent unique, dans une session persistante, avec des outils natifs : lecture et écriture de fichiers, commandes, processus, navigateur, requêtes HTTP et base de données ;
  - il remplace l'ancien pipeline à 13 passes, conservé seulement dans `benchmarks/baseline/` ;
  - quand l'agent propose la fin, l'hôte vérifie l'application : intégrité, dépendances, build, démarrage, puis tests d'acceptation (tests fournis, plus tests générés par l'hôte à partir des scénarios).
- **Résultat :** 5/5 sur le site d'exemple, en 46 min pour 3,43 CNY.
- **Objectif fixé ensuite :** moins de tokens et de temps, un taux de réussite au moins égal, sans aucune limite qui bloquerait des sites plus gros.
- **Statut :** ✅ c'est toujours l'architecture actuelle.

## v1.1 – v1.2 : premières optimisations

- **Modifications :**
  - **Mesure :** durée de chaque étape (modèle, outils, vérification), tokens d'entrée, de sortie et en cache, écrits dans `run.json` et sur stderr (ligne `Run breakdown:`). `scripts/analyze_run.py` les compare d'un run à l'autre.
  - **Outils groupés :**
    - `read_files` lit jusqu'à 8 fichiers en un appel, `write_files` en écrit jusqu'à 30 ;
    - les appels en lecture seule d'une même réponse s'exécutent en parallèle ;
    - `verify_application` enchaîne typage, build et tests backend.
  - **Contexte allégé :**
    - une lecture d'un fichier réécrit depuis, ou une commande refaite à l'identique, est remplacée par une ligne ;
    - les journaux de npm, tsc et du build sont filtrés à la source.
  - **Gabarit enrichi :**
    - briques génériques prêtes à l'emploi : erreurs HTTP uniformes, sessions en base, hachage des mots de passe, client d'API typé, routeur, champs de formulaire ;
    - un `package-lock.json` pour installer avec `npm ci`.
- **Raison :** chaque requête renvoie toute la conversation. Diviser le nombre de requêtes et alléger le contexte réduit à la fois les tokens et le temps.
- **Effet :** le run v1.2 n'a pas abouti. Il était encore en auto-test après 60 min, avec trois problèmes :
  - compactions en boucle autour de 300 Ko par requête ;
  - une commande bloquée 600 s ;
  - aucune proposition de fin.
- **Statut :**
  - ✅ mesure, outils groupés, élagage du contexte, briques du gabarit, `package-lock.json` ;
  - 🔁 le serveur du gabarit a été corrigé en v1.19 (voir plus bas).

## v1.3 : contexte maîtrisé, limites de taille retirées

- **Modifications :**
  - **Compaction :** au-delà de 80 % du contexte (240 Ko), les anciens échanges sont archivés et la conversation redescend nettement sous le seuil, pour ne pas recompacter à chaque requête.
  - **Masquage :** au-delà des 10 derniers lots d'appels, les résultats d'outils et le texte des fichiers écrits deviennent une courte mention ; leur contenu reste récupérable avec `read_artifact`.
  - **Commandes :** `run_command` limitée à 120 s par défaut ; un serveur lancé avec cette commande est refusé, avec un renvoi vers `process_start`.
  - **Fin de travail :** consigne de proposer la fin dès que l'application est vérifiée.
  - **Limites :** suppression de toutes les limites qui grandissent avec la taille du site (temps, requêtes, appels d'outils, tokens, tours de vérification, nombre de tests générés). Le délai de la suite de tests s'allonge avec le nombre de tests.
- **Raison :** les blocages du run v1.2, sans pénaliser les gros sites.
- **Effet :**
  - site d'exemple : 5/5, coût divisé par 2,6 (1,31 CNY), durée inchangée (52 min) ;
  - BookStack : 6/12, alors que tous les tests générés localement passaient. C'est la première preuve que les tests locaux ne prédisent pas les tests cachés.
- **Statut :**
  - ✅ masquage, limite de `run_command`, refus des serveurs, absence de limites de taille ;
  - 🔁 compaction modifiée en v1.18 et v1.19 (marge calculée sur la partie de travail, raisonnement raccourci) ;
  - 🔁 contexte complété en v1.16 par un plafond de 360 Ko pour les gros sites.

## v1.4 : préparation en arrière-plan

- **Modification :** dès le début de la session, l'hôte installe les dépendances du gabarit et prépare le lanceur de tests Playwright, pendant que le modèle lit les exigences. Ces installations sont ensuite réutilisées.
- **Raison :** au run v1.3, la première vérification n'arrivait qu'au bout de 35 min environ, et les installations en prenaient une partie.
- **Effet :** non mesuré isolément ; environ 40 à 55 s de préparation, faite en parallèle.
- **Statut :** ✅ gardé.

## v1.5 : navigateur sur le runner

- **Modification :** Chromium est lancé sans son bac à sable quand le processus tourne en root.
- **Raison :** sur le runner Arcbench, qui tourne en root, le navigateur de l'agent et la vérification visuelle ne démarraient pas.
- **Effet :** le navigateur de l'agent et les captures fonctionnent sur Arcbench.
- **Statut :** ✅ gardé.

## v1.6 : sous-agents en parallèle

- **Modification :**
  - outil `delegate_tasks` : l'agent principal écrit d'abord le contrat commun, puis confie jusqu'à 4 parties indépendantes à des sous-agents simultanés ;
  - chaque sous-agent a ses propres chemins d'écriture et ne lance aucune commande.
- **Raison :** écrire plus vite les parties indépendantes (demande de l'utilisateur).
- **Effet :** site d'exemple 5/5 en 29 min 24 s, contre 52 min en v1.3, mais sans qu'on puisse l'attribuer aux sous-agents : l'agent utilise rarement l'outil, et pas du tout lors du run v1.8.
- **Statut :** ✅ gardé dans les outils, peu utilisé.

## v1.7 : retour de tests pendant le travail

- **Modifications :**
  - génération des tests de l'hôte en parallèle (plusieurs exigences à la fois) ;
  - outil `run_acceptance_tests` : l'agent lance lui-même un tour de vérification (installation, build, démarrage sur une base neuve, tous les tests) et reçoit chaque échec avec l'identifiant de l'exigence ;
  - après plusieurs vérifications manuelles (curl, base de données, navigateur) une fois le build réussi, un rappel invite l'agent à utiliser cet outil ;
  - règle pour le générateur : ne vérifier une URL que si l'exigence la donne.
- **Raison :** l'agent passait de longues minutes à tester ses parcours à la main.
- **Effet :** BookStack 6/182 en 68 min, dont 47 min dans `run_acceptance_tests`. Chaque tour durait 8 à 16 min, parce qu'un élément introuvable faisait attendre le test jusqu'à sa limite de 30 s.
- **Statut :**
  - ✅ outil, rappel et règle des URL gardés ;
  - 🔁 génération portée à 8 requêtes simultanées en v1.18 ;
  - 🔁 `run_acceptance_tests` reçoit le paramètre `disputes` en v1.18.

## v1.8 : contrat d'interface

- **Modifications :**
  - **Contrat :** l'hôte extrait, sans appel au modèle, les éléments que les exigences nomment avec un rôle, sous les formes `"Book list"(role=region)` ou `Page list (region)`. L'agent les reçoit dans son premier message sous forme de localisateurs exacts, et le générateur de tests doit les utiliser tels quels.
  - **Tests locaux sur 3 workers** et une base partagée, comme les tests cachés le laissaient supposer, pour faire apparaître les listes tronquées et les problèmes de concurrence.
  - **Règles de livraison :** textes exacts, placeholders décrits, aucune pagination non demandée, navigation exigée toujours appliquée, aucun cas particulier pour satisfaire un test.
- **Raison :** les tests cachés localisent les éléments par rôle et nom exacts.
- **Effet :**
  - site d'exemple : 5/5 en 20 min pour 1,28 CNY ;
  - **BookStack : 2/12, en recul.** Le contrat avait perdu la mention « equivalent link also allowed », les tests générés exigeaient un bouton, et l'agent a imbriqué des `span[role=button]` dans des liens pour les satisfaire.
  - **Leçon :** toute règle qui rend les tests générés plus stricts sur la structure pousse l'agent à bricoler le balisage.
- **Statut :**
  - 🔁 contrat gardé, puis étendu : alternatives en v1.12, zones nommées en v1.21, contrôles dans leur zone en v1.23 ;
  - ✅ 3 workers gardés ;
  - 🔁 règles de livraison gardées, sauf « un lien pour ouvrir une page », remplacée en v1.22.

## v1.9 : lisibilité et vitesse de vérification

- **Modifications :** lignes de progression de chaque étape de vérification sur stderr ; relecture en parallèle des fichiers de tests en échec.
- **Raison :** suivre un run depuis le journal du runner, et raccourcir les tours.
- **Effet :** non mesuré isolément.
- **Statut :** ✅ gardé ; les relectures sont bornées en v1.17.

## v1.10 : fin de tour automatique

- **Modifications :**
  - `finish_on_pass` : dès qu'une exécution de `run_acceptance_tests` passe en entier et que chaque scénario a un test, le tour de l'agent se termine et l'hôte fait la vérification finale depuis un état propre ;
  - images de référence décrites d'avance par le modèle de vision, toutes en parallèle et avec un cache, au lieu d'être consultées une à une ;
  - variante de mesure avec raisonnement `none`.
- **Raison :** au run v1.8, l'agent passait encore 11 min à peaufiner après des tests verts, et 3 min à consulter les images.
- **Effet :** la variante `none` donne 5/5 en 27 min pour 2,75 CNY, avec 334 requêtes et 8 tours d'échecs identiques. Elle est donc plus chère et plus lente que `low`.
- **Statut :**
  - ✅ `finish_on_pass` et descriptions d'images gardés ;
  - ❌ variante `none` abandonnée.

## v1.11 : délai par action

- **Modification :** chaque action d'un test de l'hôte (clic, saisie) attend au plus 8 s, au lieu de toute la durée du test.
- **Raison :** les tours de 8 à 16 min de la v1.7.
- **Effet :** un tour de vérification passe à environ 1 min sur les runs suivants (mesuré sur Stack Overflow et BookStack).
- **Statut :** ✅ gardé.

## v1.12 : alternatives et sobriété du balisage

- **Modifications :**
  - le contrat conserve les alternatives annoncées par l'exigence (« lien ou bouton », exprimé par `.or()`) ;
  - interdiction d'imbriquer des éléments interactifs ou d'ajouter des rôles pour satisfaire un test ;
  - le générateur vérifie des résultats (textes, titres, entrées de liste, persistance), pas du balisage ;
  - pour un contrôle sans rôle, il accepte lien ou bouton.
- **Raison :** le recul de la v1.8.
- **Effet :** voir v1.13.
- **Statut :**
  - ✅ alternatives annoncées, interdiction d'imbriquer, vérification des résultats ;
  - 🔁 l'acceptation « lien ou bouton » pour les contrôles sans rôle est remplacée en v1.22 par « bouton ».

## v1.13 : champs et répétitions

- **Modifications :**
  - règles pour le générateur : localiser un champ mot de passe par son libellé, en partant de l'idée qu'il n'a pas le rôle textbox ; saisir les dates au format de l'exigence ;
  - quand le même échec revient 3 fois de suite, l'agent est averti que le test est peut-être faux et qu'il ne doit pas casser un comportement correct pour le satisfaire.
- **Raison :** l'agent avait transformé des champs mot de passe en champs texte pour satisfaire un test généré.
- **Effet :**
  - site d'exemple : **5/5 en 5 min 15 s pour 0,52 CNY**, le meilleur résultat ;
  - BookStack : 6/12 en 36 min, un plateau déjà atteint en v1.3 et v1.7.
- **Statut :**
  - ❌ règle du mot de passe remplacée en v1.18 : elle était fausse, car Playwright donne le rôle textbox à un champ mot de passe ;
  - ✅ règle des dates gardée ;
  - 🔁 avertissement gardé, son texte renvoie depuis la v1.18 vers la contestation d'un test.

## v1.14 : tests sans navigation refusés

- **Modification :** un test généré dont aucune étape n'ouvre l'application (`page.goto`, directement ou dans une fonction du fichier) est refusé dès sa génération, et le relecteur sait reconnaître ce cas.
- **Raison :** 20 min perdues sur un test qui s'exécutait sur une page vide.
- **Effet :**
  - **Stack Overflow : 0/28**, en 99 min pour 17,20 CNY ;
  - **BookStack complet : 0/35**, en 59 min pour 10,86 CNY.
  - La cause, sans lien avec ce changement, était commune aux deux : sur ces gros sites, les exigences dépassaient la limite pour rester dans le message initial. L'agent ne recevait qu'un catalogue et les relisait en boucle (435 lectures d'exigences, 107 compactions, seulement 2 `write_files`). L'application livrée était presque le gabarit vide.
- **Statut :** ✅ gardé.

## v1.15 : images de référence (essai, en partie retiré)

- **Modifications :**
  - **Images jointes :** les images de référence, réduites, sont jointes à la conversation en plus de leurs descriptions. Si le fournisseur refuse les images, l'agent continue avec les seules descriptions.
  - **Retour visuel :** quand les tests passent, `run_acceptance_tests` renvoie une fois les différences visuelles entre les pages et les références.
  - **Pages à paramètres :** pour une route comme `/books/:id`, la vérification visuelle capture une vraie page trouvée par un lien.
- **Raison :** fidélité visuelle, demandée pour BookStack, dont les échecs pouvaient venir de la structure des pages.
- **Effet :** BookStack lite arrêté à la main, sans score. Après 30 min d'écriture, l'agent a fait plus de 17 tours sur un seul test généré dont le titre changeait à chaque exécution (« Test not found in the worker process »). Ce blocage est sans rapport avec les images, mais l'apport visuel n'a donc jamais été démontré.
- **Statut :**
  - ❌ images jointes : retirées en v1.17 à la demande de l'utilisateur ; `reference_images: describe`, l'agent reçoit seulement les descriptions ;
  - ❌ retour visuel : désactivé en v1.17 (`acceptance.visual_feedback: false`), le code reste en place ;
  - ❌ capture des pages à paramètres : inactive, puisque la comparaison visuelle est coupée depuis la v1.19.

## v1.16 : gros sites et boucles de réparation

- **Modifications :**
  - **Exigences entières :** elles restent dans le message initial tant qu'elles tiennent dans 30 % du contexte, porté à 360 Ko. La fenêtre de travail de 240 Ko s'ajoute au-dessus.
  - **Lecture des exigences :**
    - `read_requirement` ne répète plus les exigences parentes déjà montrées ;
    - une section entière se lit en un appel (`descendants`) ;
    - ces lectures ne sont plus masquées, et la mémoire après compaction n'invite plus à tout relire.
  - **Avertissement** après 12 étapes de suite sans écrire de fichier.
  - **Pas de nouvelle vérification** sur des sources inchangées.
  - **Tests générés :** leur titre doit être une chaîne constante.
  - **Empreinte d'un échec :** calculée par scénario ou par fichier, et non plus par titre de test.
  - **Arrêts :**
    - le tour de l'agent s'arrête après 5 échecs identiques de suite ;
    - le driver s'arrête après 6 tours identiques.
- **Raison :** les boucles « lire → compacter → oublier → relire » de la v1.14, et le test sans fin de la v1.15.
- **Effet :** sur Stack Overflow, l'agent écrit tôt (première vérification à 13 min) : la boucle de lecture est réglée. Mais le résultat est **0/182**, en 101 min pour 12,93 CNY, avec 9 tours de réparation :
  - 3 tours sur des sources inchangées, de 7 min chacun ;
  - des relectures bloquées environ 6 min à chaque tour par des délais du fournisseur ;
  - jamais de tour depuis un état propre.
  
  La cause du 0 n'était pas visible à ce moment-là.
- **Statut :** ✅ tout est gardé ; les arrêts sont complétés en v1.18 et v1.24.

## v1.17 : vérification plus sobre

- **Modifications :**
  - retrait des fonctions d'images de la v1.15 (voir plus haut) ;
  - `run_acceptance_tests` renvoie immédiatement le dernier rapport si aucun fichier source n'a changé ;
  - le premier tour de l'agent se fait depuis un état propre, comme au déploiement : sources seules, build refait, base par défaut ;
  - chaque tour exécute toute la suite, et plus seulement les fichiers en échec ;
  - relectures de tests limitées à 180 s par tour et 2 par fichier, avec une empreinte d'erreur qui ignore les durées et les identifiants ;
  - le driver ne revérifie jamais une révision en échec inchangée ;
  - stderr liste chaque test en échec avec sa première ligne d'erreur.
- **Raison :** les tours répétés, les relectures bloquées et les 17 scénarios jamais retestés de la v1.16.
- **Effet :** deux runs locaux, sans envoi Arcbench :
  1. délai de 120 s par requête au modèle : la longue réponse qui écrivait l'application a expiré trois fois, d'où une panne du fournisseur à la 6ᵉ minute et une application vide ;
  2. délai porté à 600 s : application écrite en 12 min, puis **87 min de réparation contre des tests générés faux**, sans fin. Arrêt manuel à 99 min, avec 19,1 M tokens en entrée et 413 requêtes. Une sonde écrite à la main dans le style des tests cachés montrait que l'application était correcte.
  
  Détail dans `PROBLEMES_RUN_LOCAL_V117.md`.
- **Statut :** ✅ tout est gardé.

## v1.18 : des tests générés plus justes, une boucle qui s'arrête

- **Modifications :**
  - **Exigences référencées :** pour chaque scénario, le générateur et le relecteur reçoivent les exigences dont il dépend (`dependencies`, `\ref[requirement]`), de proche en proche, jusqu'à 10. *Raison :* les tests créaient des questions avec un corps de 40 caractères alors qu'une autre exigence impose 220, si bien que l'application les refusait à raison.
  - **Page au moment de l'échec :**
    - l'hôte lit l'instantané d'accessibilité que Playwright écrit (`error-context.md`), sans jamais le code du test ;
    - le relecteur reçoit la page, l'agent ses alertes (« The page showed: … »).
    
    *Raison :* le message de validation qui expliquait les échecs n'était vu par personne.
  - **Corrections qui affaiblissent un test refusées :** une correction qui retire des assertions (`expect`) ou des noms exacts est rejetée. *Raison :* 25 relectures sur 27 assouplissaient les tests sans trouver la cause.
  - **Tests écartés :** un test que ses relectures ont jugé faux et qui échoue toujours ne compte plus contre l'application.
  - **Contestation :** l'agent peut contester un test avec un argument (`run_acceptance_tests` avec `disputes`). Un relecteur juge l'argument sur pièces.
  - **Arrêt sans progrès :** le run s'arrête après 3 tours sans nouveau record de tests réussis. *Raison :* les échecs oscillaient (16, 17, 16, 18…) sans jamais se répéter à l'identique.
  - **Raisonnement raccourci :** au-delà des 3 derniers échanges, le raisonnement passé de l'agent est réduit à quelques lignes. *Raison :* il représentait la plus grande partie du contexte et était renvoyé à chaque requête.
  - **Journal tenu par l'hôte**, ajouté à la mémoire de travail : carte du code (fichiers, exports, tables, routes) et historique des vérifications. *Raison :* 21 compactions en 100 min, avec des notes de travail vides.
  - **Fournisseur :** délai de 600 s par requête au modèle, reprise unique après une erreur du fournisseur, aucune vérification si rien n'a été écrit.
  - **Génération des tests :** 8 requêtes simultanées au lieu de 4.
- **Effet :** run local sur Stack Overflow terminé seul et accepté en **55 min** (contre 99 min sans fin), avec **10,0 M tokens** en entrée (contre 19,1 M) et 226 requêtes (contre 413).
- **Statut :** ✅ gardé, avec deux modifications :
  - 🔁 tests écartés : montrés à l'agent en v1.19, règle de mise à l'écart corrigée en v1.20 ;
  - 🔁 arrêt sans progrès : complété en v1.24.

## v1.19 : gabarit corrigé et tests écartés rendus visibles

- **Modifications :**
  - **Gabarit :** les routes côté client sont servies avec `sendFile("index.html", { root })`. *Raison :* avec un chemin absolu, toute page rechargée ou ouverte directement renvoyait `{"error":"Invalid request"}` dès qu'un dossier du chemin commençait par un point, ce qui est toujours le cas en vérification locale.
  - **Tests écartés montrés à l'agent** une fois, avant la fin, avec ce qu'ils cherchaient. *Raison :* 2 des 4 tests écartés au run v1.18 révélaient de vrais défauts (un bouton « Log in » en double, un avatar sans image).
  - **Règles pour l'agent :**
    - un élément du contrat est unique sur sa page ;
    - un avatar, un logo ou une icône est une image ;
    - chaque information nommée (auteur, date) a son propre élément.
  - **Tests parallèles :** les valeurs qu'ils partagent (score, réputation) sont vérifiées comme un minimum. *Raison :* deux tests votaient en même temps pour le même auteur et se faussaient mutuellement.
  - **Raisonnement :** la compaction raccourcit aussi celui des échanges qu'elle garde (sauf le dernier).
  - **Page à l'échec :** une page de quelques lignes (JSON brut) est transmise entière.
  - **Vérification :** pas de nouveau tour sur une révision qui vient de passer.
  - **Comparaison visuelle coupée.**
- **Effet :**
  - **Stack Overflow, 10/27 (37 %)**, en 33 min pour 4,56 CNY (contre 0 avant) ;
  - run local sur BookStack accepté en 30 min, avec 2,3 M tokens.
  - L'analyse du `project.zip` d'Arcbench donne la cause des 17 échecs. Toutes les connexions réussissaient (sessions en base), mais aucune question n'avait été créée. Le scénario de connexion attend « Question feed appears », et l'application n'avait pas de zone de ce nom : chaque test connecté attendait jusqu'à sa limite de 10 s.
- **Statut :** ✅ gardé.

## v1.20 : règle de mise à l'écart plus stricte, placeholders

- **Modifications :**
  - **Mise à l'écart :** un test n'est écarté que si **toutes** ses relectures l'ont réellement corrigé. Une relecture qui accuse l'application, ou une correction refusée, le laisse compter. *Raison :* au run BookStack, une relecture avait reconnu un défaut de l'application, puis une seconde avait proposé d'affaiblir le test, et le test avait été écarté.
  - **Placeholders :** quand une exigence dit que des champs sont « also exposed with those placeholders », chacun reçoit son nom comme placeholder, et le générateur le vérifie. *Raison :* le champ « Page title » n'en avait pas.
- **Effet :** voir v1.21.
- **Statut :** ✅ gardé.

## v1.21 : zones nommées

- **Modification :**
  - l'hôte extrait les parties de page que les scénarios nomment sans rôle : « in **Question feed** », « in **Main navigation** » ;
  - les champs (« fill X ») et les noms déjà dans le contrat sont exclus ;
  - l'agent doit donner à chaque zone un élément portant ce nom exact, et les tests générés s'en servent pour cibler leurs localisateurs ;
  - l'extraction a été vérifiée sur les 6 sites de la compétition.
- **Raison :** l'absence de la zone « Question feed » expliquait les 17 échecs de la v1.19.
- **Effet :**
  - **Stack Overflow : 46,4 %** (contre 37 %), en 41 min pour 4,56 CNY. La zone existe désormais, mais le bouton « Ask Question » est placé juste au-dessus d'elle au lieu d'être dedans : les tests cachés ne créent toujours aucune question.
  - **BookStack : 6/12**, en 13 min pour 1,15 CNY. Le code des tests cachés montre la cause : `button(page, 'Edit')`. Les tests cherchent un **bouton** « Edit », que l'agent avait fait en lien en suivant notre propre consigne.
- **Statut :** ✅ gardé, complété en v1.23.

## v1.22 : boutons par défaut

- **Modification :**
  - un contrôle n'est un lien que si l'exigence l'appelle ainsi (« Register link », `role=link`) ou s'il appartient à un menu de navigation ;
  - tous les autres contrôles nommés (« Edit », « New Page », « Cancel »…) sont des boutons, même s'ils changent de page ;
  - la règle s'applique à l'agent, à la notice du contrat, au générateur et au relecteur.
- **Raison :** la convention se vérifie sur trois sites :
  - site d'exemple : `link('Register')`, mais `button('Next step')` et `button('Logout')` ;
  - BookStack : `button('Edit')` ;
  - Stack Overflow : le lien « Questions » de la navigation passait.
  
  Notre consigne de la v1.8 disait l'inverse.
- **Effet :** non mesuré.
- **Statut :** ✅ gardé.

## v1.23 : contrôles placés dans leur zone

- **Modifications :**
  - **Paires « contrôle → zone » :** l'hôte les extrait des scénarios (« Click **Ask Question** in **Question feed** », « **Question feed** exposes **Ask Question** », « Follow **Questions** in **Main navigation** »), en ne gardant que des zones connues. L'agent reçoit la liste exacte des contrôles à mettre *dans* chaque zone, sur chaque page où elle apparaît ; le générateur les cherche au même endroit.
  - **Règles pour l'agent :**
    - ce qu'une exigence décrit comme partie d'une zone est imbriqué dedans ;
    - une zone placée sur plusieurs pages existe sur chacune ;
    - une valeur nommée a une étiquette visible devant elle, comme dans le produit d'origine.
- **Raison :**
  - le bouton « Ask Question » hors de la zone en v1.21 ;
  - les vérifications des tests cachés sur la page d'une question : un texte commençant par « Viewed », le mot « badge », la zone « Author » à l'intérieur de « Question post ».
- **Effet (envoi sur les 6 sites) :**
  - **BookStack 100 %** en 8 min (6/12 en v1.21) : les boutons « Edit » et « New Page » de la v1.22 étaient la cause ;
  - **Keep 100 %** en 18 min ;
  - **Stack Overflow 85,7 %** en 29 min (46,4 % en v1.21) : « Ask Question » est désormais dans « Question feed » ;
  - **PrestaShop 87,5 %**, mais en 177 min pour 12,9 M tokens ;
  - **Ctrip 30 %** en 35 min, le point faible restant ;
  - **12306 (49 scénarios), aucun score.** Le run a été arrêté à la main après environ 8 h :
  - chaque requête au modèle prenait environ 1 min 45 ;
  - l'agent ne lançait un tour de vérification que toutes les 25 min à 2 h ;
  - il a passé jusqu'à 96 étapes de suite sans écrire ;
  - l'arrêt sans progrès, compté en tours, ne s'est jamais déclenché.
- **Statut :** ✅ gardé.

## v1.24 : arrêt sans progrès sur les gros sites

- **Modifications :**
  - **Arrêt sans progrès compté aussi en requêtes :** le run s'arrête après 150 requêtes au modèle sans nouveau record, avec au moins un tour sans record, dans le driver comme dans `run_acceptance_tests`.
  - **Fin de tour forcée :** après 48 étapes sans écrire, le tour de l'agent se termine et l'hôte vérifie l'application telle quelle. Le retour de cette vérification remplace la lecture, et ce tour compte pour l'arrêt sans progrès.
  - **Règles pour l'agent :**
    - un choix parmi des options fixes est un `<select>` natif, parce que les tests d'exemple d'Arcbench utilisent `selectOption` ;
    - un contrôle cliqué par son nom apparaît une seule fois sur la page (un calendrier affichait deux boutons pour la même date).
- **Raison :** le run 12306 de la v1.23.
- **Effet :** non mesuré. Ce ne sont pas des plafonds de taille : chaque nouveau record remet les compteurs à zéro.
- **Statut :** ✅ version actuelle.

---

## Leçons générales

1. **Les tests générés localement ne prédisent pas le score caché.** Ils servent à corriger l'application et à arrêter les boucles, mais seuls les envois Arcbench mesurent le résultat. Depuis la v1.19, chaque envoi est analysé avec trois sources :
   - le **code des tests cachés en échec** (panneau « Test Results » de la page de la soumission) ;
   - le **`project.zip`**, qui contient le code livré et la base de données après les tests ;
   - le **JSON des résultats** (onglet Réseau du navigateur).
   
   Ce code sert uniquement au diagnostic : il n'est jamais transmis à l'agent.
2. **Les tests cachés suivent des conventions stables**, intégrées depuis :
   - rôle et nom exacts ;
   - boutons par défaut, liens seulement s'ils sont annoncés comme tels ;
   - zones nommées dans les scénarios, avec les contrôles placés à l'intérieur ;
   - placeholders quand ils sont annoncés ;
   - 10 s maximum par test, avec un seul worker.
3. **Durcir les tests générés sur la structure pousse l'agent au bricolage** (v1.8). Ce qui marche : donner à l'agent les noms et l'emplacement exacts tirés des exigences.
4. **Chaque correction reste générique.** Les sites ne servent qu'au diagnostic. Les règles extraites automatiquement (zones nommées, contrôles dans leur zone) ont été vérifiées sur les 6 sites de la compétition.

Détails par run : `SUIVI_RUNS_LOCAUX.md` ; problèmes des runs v1.17 : `PROBLEMES_RUN_LOCAL_V117.md` ; recherche et pistes : `PROPOSITIONS_AMELIORATION_V1.md`, `RECHERCHE_ACCELERATION_AGENT.md`.

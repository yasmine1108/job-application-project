# Pipeline Automatisé de Candidatures (Job Application Pipeline)

Pipeline de bout en bout qui automatise la recherche d'emploi : extraction du profil candidat depuis un CV, scraping d'offres sur plusieurs plateformes (LinkedIn et Tanitjobs), matching intelligent via LLM, génération de lettres de motivation personnalisées, et candidature automatique.

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Architecture du projet](#architecture-du-projet)
- [Fonctionnement du pipeline](#fonctionnement-du-pipeline)
- [Description des modules](#description-des-modules)
- [Modèles de données](#modèles-de-données)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Format des sorties](#format-des-sorties)
- [Limitations connues](#limitations-connues)

## Vue d'ensemble

Le projet automatise le processus complet de candidature en ligne :

1. **Extraction du CV** — lecture d'un fichier CV (PDF ou DOCX ou image) et extraction structurée du profil (informations personnelles, formation, expériences, projets, compétences, certifications, langues) via un LLM.
2. **Scraping d'offres** — collecte d'offres d'emploi sur des plateformes comme TanitJobs et LinkedIn.
3. **Matching** — filtrage déterministe (statut de l'offre, langue, localisation, préférences) puis notation par un LLM sur trois dimensions : adéquation compétences, expérience, formation.
4. **Génération de lettres de motivation** — rédaction automatique adaptée à chaque offre, dans la langue de l'annonce.
5. **Candidature automatique** — remplissage et soumission des formulaires de candidature (avec un mode `dry_run` pour tester sans soumettre réellement).

## Architecture du projet

```
agent_project/
├── app.py                         # Interface Streamlit et flux utilisateur complet
├── main.py                        # Point d'entrée script pour exécuter le pipeline
├── gui_utils.py                   # Adaptateurs GUI, gestion des CV et profils en cache
├── config/
│   └── settings.py                # Configuration et variables d'environnement
├── src/
│   ├── models.py                  # Modèles Pydantic du profil candidat
│   ├── models_job.py              # Modèles des offres, résultats et préférences
│   ├── pipeline.py                # Orchestration de bout en bout
│   ├── candidate_identity.py      # Vérification des coordonnées obligatoires
│   ├── application_logging.py    # Journalisation append-only des candidatures
│   ├── data_helpers.py            # Lecture et recherche dans les sorties JSON
│   ├── shared.py                  # Utilitaires partagés
│   ├── ai_modules/
│   │   ├── cv_parser.py           # Extraction brute du CV
│   │   ├── cv_extractor.py        # Extraction structurée du profil via LLM
│   │   ├── job_offer_extractor.py # Extraction structurée des offres via LLM
│   │   └── cover_letter.py        # Génération des lettres de motivation
│   ├── llm/
│   │   ├── base.py                # Contrat commun des fournisseurs LLM
│   │   ├── fallback.py             # Fallback entre plusieurs fournisseurs
│   │   ├── gemini_provider.py      # Fournisseur Gemini
│   │   ├── groq_provider.py        # Fournisseur Groq
│   │   ├── openai_strict_schema.py # Sorties structurées compatibles OpenAI
│   │   └── providers.py             # Types et utilitaires des fournisseurs
│   ├── matchers/
│   │   ├── matcher.py              # Filtres déterministes et scoring LLM
│   │   ├── country_normalize.py    # Normalisation des pays
│   │   └── date_normalize.py       # Normalisation des dates d'offres
│   ├── orchestrator/
│   │   ├── orchestrator.py         # Coordination des exécutions
│   │   └── worker_cli.py            # Worker en ligne de commande
│   └── scrapers/
│       ├── base_scraper.py         # Interface et comportement communs
│       ├── job_board_scraper.py    # Registre et sélection des scrapers
│       ├── tanitjobs.py             # Scraper et auto-apply TanitJobs
│       ├── linkedin.py              # Scraper et auto-apply LinkedIn
│       └── registery_setup.py       # Enregistrement des job boards
├── tests/                          # Tests unitaires et d'intégration
└── data/
        ├── cv/                         # CV sources et manifeste
        ├── profiles/                   # Profils candidats mis en cache
        ├── cache/                      # Documents intermédiaires extraits
        └── outputs/                    # Offres, matchs et journaux JSON
```

## Fonctionnement du pipeline

Le fichier `pipeline.py` orchestre l'ensemble des étapes pour **un candidat** et **un mot-clé de recherche** donnés :

```
CV → Profil candidat
        │
        ▼
┌─────────────────────────────┐
│ 1. Scraping des offres       │  (tanitjobs.py, linkedin.py)
│    → liste de RawJob         │
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 2. Extraction structurée(llm)     │  (job_offer_extractor, externe)
│    RawJob → JobOffer          │
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 3. Matching (llm)           │  (matcher.py)
│    Filtres → Scoring LLM      │
│    → MatchResult               │
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 4. Tiering par score           │
│    - Score élevé → auto-apply  │
│    - Score moyen → à confirmer (n'est pas encore implémenté) │
│    - Score faible → écarté       │
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 5. Candidature automatique     │  (auto_apply + cover_letter.py)
│    Formulaire + lettre de       │
│    motivation générée            │
└─────────────────────────────┘
```

Chaque étape persiste son état sur disque (JSON) pour permettre une reprise après crash sans perte de progression, et pour éviter de retraiter des offres/candidatures déjà effectuées.

## Description des modules

### `cv_parser.py`
Extrait le contenu brut d'un CV (PDF ou image) :
- Conversion en Markdown via `pymupdf4llm`.
- Extraction des hyperliens (LinkedIn, GitHub, portfolio).
- Détection des tableaux.
- OCR (français + anglais, via Tesseract) pour les images pures.

### `cv_extractor.py`
Transforme le contenu brut (`ParsedDocument`) en `CandidateProfile` structuré. Utilise **un appel LLM local (qwen2.5:7b) distinct par section** (infos personnelles, formation, expérience, projets, compétences, certifications, langues) plutôt qu'un seul gros appel, afin que chaque prompt reste ciblé et fiable.

Post-traitements déterministes après extraction :
- `enforce_standard_years_of_study` — corrige la durée d'études selon le niveau de diplôme (ex : Diplôme d'Ingénieur = 5 ans), plutôt que de se fier au calcul du LLM à partir des dates.
- `normalize_profile_skills` — normalise les noms de compétences afin de faciliter la comparaison du Matcher.
- `populate_skill_evidence` — retrouve, par recherche textuelle (pas d'inférence LLM), les passages du CV qui justifient chaque compétence déclarée.

### `models.py`
Définit les modèles Pydantic du profil candidat : `PersonalInformation`, `Education`, `Experience`, `Project`, `Skill`, `Certification`, `SpokenLanguage`, assemblés dans `CandidateProfile`. `MatchingProfile` est une vue allégée du profil, utilisée spécifiquement pour le matching (sans les données d'identité).

### `country_normalize.py`
Normalise les noms de pays (ex : "Tunisie", "UK", "USA") vers un code ISO 3166-1 alpha-2, via `pycountry` et les données de localisation de `babel` (dont les noms français). Utilisé par le matcher pour comparer la localisation d'une offre à la préférence du candidat sans faux négatifs liés aux variantes de nom.

### `matcher.py`
Cœur de la logique de matching, en deux temps :
1. **Filtres déterministes et gratuits** (`apply_hard_filters`) — rejettent d'emblée les offres fermées, ne correspondant pas aux préférences (type de contrat, mode de travail), trop éloignées géographiquement, ou exigeant une langue non maîtrisée. Comme l'application est visée principalement aux candidats tunisiens et comme la plus part de ces candidats maitrise au moin les bases des langues arabe, francaise et anglaise et en conséquent ne les mentionnent pas dans leurs CV alors le hard filter ne s'applique que si l'offre de travail demande un niveau de maitrise très avancé voire native.
2. **Scoring par LLM** (`Matcher.match_batch`) — les offres restantes sont envoyées par lots au LLM, qui note chaque offre sur trois dimensions (`skills_fit`, `experience_fit`, `education_fit`) avec justification. Le score global est calculé **déterministiquement** ensuite (`compute_overall_score`), selon une pondération fixe (50 % compétences / 30 % expérience / 20 % formation) — pas par le LLM lui-même, pour garder l'agrégation fiable et ajustable sans nouvel appel au modèle.

Inclut aussi le calcul de distance entre gouvernorats tunisiens (formule de Haversine) pour le filtre de distance maximale de trajet selon les préférences du candidat.

### `cover_letter.py`
Génère une lettre de motivation sur mesure pour chaque candidature, à partir de :
- Faits vérifiables du profil candidat (jamais inventés).
- L'analyse de matching (pourquoi cette offre correspond).
- Les données structurées de l'offre (source principale) et un extrait de la description brute.

La lettre est rédigée dans la langue de l'offre (français ou anglais). Génération conditionnée à un score minimum (`Settings.MIN_OVERALL_SCORE_FOR_AUTO_LETTER`) pour ne pas perdre des tokens de l'API de LLM sur des match qui sont de mauvaise qualité.

### `tanitjobs.py`
Scraper Playwright pour TanitJobs.com : connexion, recherche par mot-clé, collecte des cartes d'offres (avec pagination), extraction des détails (description, exigences, date d'expiration), et remplissage/soumission du formulaire de candidature.

### `linkedin.py`
Scraper Playwright pour LinkedIn : connexion, recherche, collecte des identifiants d'offres, extraction via le DOM, et un flux de candidature "Easy Apply" multi-étapes (informations personnelles, CV, lettre de motivation en PDF, expérience...).

### `application_logging.py`
Journal **append-only** de toutes les tentatives de candidature (réelles ou en `dry_run`), conservant l'historique complet. La duplication des applications pour un même offre de travail sont permis lors des dry_run (remplir le formulaire sans réellement le soumettre) à raison de debugging.

### `pipeline.py`
Orchestre les étapes ci-dessus pour un candidat et un mot-clé donnés. Répartit les résultats de matching en trois paliers selon des seuils configurables (`high_score_threshold`, `mid_score_threshold`), et déclenche la candidature automatique uniquement pour le palier « score élevé ». J'ai envisagé un tier de matches qui ont des scores moyennes et dont leurs applications ont besoin de la confirmation du candidat. Faute de temps, ce tier n'est pas encore implémenté même si dans les paramètres de la méthode il y'a une variable pour le threshold de ce tier.

## Modèles de données

| Modèle | Rôle |
|---|---|
| `CandidateProfile` | Profil complet extrait du CV |
| `MatchingProfile` | Sous-ensemble du profil utilisé pour le matching |
| `JobOffer` | Offre d'emploi structurée (définie dans `models_job.py`) |
| `RawJob` | Offre brute telle que scrapée (titre, description, etc.) |
| `MatchJudgment` | Notation LLM d'une offre (3 dimensions + résumé) |
| `MatchResult` | `MatchJudgment` + score global calculé + priorité de candidature (offre augmente pour les offres d'emploi de LinkedIn qui sont Easy Apply par exemple) |
| `RejectedMatch` | Offre écartée par un filtre déterministe, avec raison |
| `ApplicationLog` | Trace d'une tentative de candidature (dry-run ou réelle) |

## Prérequis

- Python 3.10+
- [Playwright] (scraping des plateformes d'emploi)
- `pymupdf` / `pymupdf4llm` (extraction PDF)
- `pydantic`
- `pycountry`, `babel` (normalisation des pays)
- `langchain-core` (prompts structurés)
- Un accès LLM configuré via `FallbackLLM` (`src/llm/fallback.py`). Fallback sert à automatiquement changer le modèle de LLM utilisé si le modèle actuel renvoie un code d'erreur, de saturation, ou de fin de la quota.
- Tesseract-OCR (pour l'OCR des CV en image), avec les modèles de langue `fra` et `eng`

## Installation

```bash
git clone https://github.com/yasmine1108/job-application-project.git
cd agent_project
python -m venv venv
venv\Scripts\activate 
pip install -r requirements.txt
playwright install
```

Configurer les identifiants et clés API dans un fichier `.env` (voir `config/settings.py`), notamment :
- Identifiants TanitJobs (`TANITJOBS_EMAIL`, `TANITJOBS_PASSWORD`)
- Identifiants LinkedIn (`LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD`)
- Clé(s) API du/des LLM utilisé(s)

## Configuration

Les principaux paramètres ajustables se trouvent dans `config/settings.py` et dans les arguments de `run_pipeline_for_candidate` :

| Paramètre | Description |
|---|---|
| `high_score_threshold` | Score à partir duquel une candidature est automatique |
| `mid_score_threshold` | Score à partir duquel une offre est proposée pour confirmation manuelle |
| `dry_run` | Si `True`, simule la candidature sans soumettre réellement |
| `board_domains` | Limite le scraping à certaines plateformes (e.g : board_domains=["tanitjobs.com"] pour limiter la recherche à TanitJobs ou board_domains=None pour rechercher sur toutes les plateformes disponibles) |
| `MIN_OVERALL_SCORE_FOR_AUTO_LETTER` | Score minimum pour générer une lettre de motivation |

## Utilisation

Exemple minimal d'exécution du pipeline pour un candidat se trouve dans le fichier main.py .

## Format des sorties

Toutes les sorties sont écrites en JSON dans `data/outputs/` :

- `tanitjobs_links.json` / `linkedin_links.json` — liens d'offres collectés spécifiques à une plateforme donnée.
- `tanitjobs_raw_job_list.json` / `linkedin_raw_job_list.json` — offres avec détails complets spécifiques à une plateforme donnée.
- `matches.json` — résultats de matching (`results` + `rejected`) par candidat.
- `applications.json` — historique complet des tentatives de candidature.
- `<nom_cv>_profile.json` — profil candidat extrait, mis en cache.

## Limitations connues

- Le mode `dry_run` est activé par défaut pour éviter toute soumission accidentelle — bien vérifier avant de passer en mode réel.
- Les scrapers LinkedIn/TanitJobs reposent sur des sélecteurs DOM/XPath qui peuvent casser en cas de changement d'interface côté plateforme surtout pour Linkedin car ils change leur DOM frèquemment pour bloquer les bots.
- Le flux LinkedIn "Easy Apply" ne gère pas encore les questions additionnelles personnalisées posées par certains recruteurs. Une solution sera d'implémenter un OCR qui lit les questions, les répond et puis les écris dans le formulaire
- La détection du statut « offre encore ouverte » est mis à jour correctement pour Linkedin (automatiquement détecte le texte "no longer accepting applications sur la page et met à jour le statut) mais le mis à jour n'est pas encore implémenté pour TanitJobs. TanitJobs fournit une date d'expiration, un cron job qui compare la date actuelle et celle de l'expiration searait suffisant pour cette tâche.
- Le matching LLM peut être sensible au découpage en lots (`batch_size`) : un lot trop grand augmente le risque d'erreurs de structuration de sortie.
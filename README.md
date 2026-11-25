# AVA — Suivi de validation des propositions de projet

Application web (Flask + SQLite) qui suit la validation d'une proposition de
projet par plusieurs utilisateurs.

## Fonctionnement

1. **Accueil** : deux possibilités — **Nouveau projet** ou **Tableau de pilotage** (l'accès aux **Archives** se fait aussi depuis l'accueil).
2. **Fiche projet** :
   - informations : nom du projet, date, nom du créateur et son adresse mail, UP concernée (usine), descriptif détaillé (champ large, supporte plus de 800 mots), délai de lancement cible (en mois à partir de la validation définitive), gain total estimé (€) ;
   - valideurs internes **Agro** : Développeur, Directeur commercial, Adhérent ;
   - valideurs ITMAI : Acheteur, Responsable marketing, CEQ (nom, prénom, adresse mail) ;
   - bouton **Valider la fiche** qui active le workflow.
3. **Workflow de validation** :
   - un mail « Vous avez un projet AVA à valider » (avec un lien unique vers la
     page de validation) est envoyé aux trois valideurs internes Agro ;
   - la page de validation affiche les informations du projet et demande
     **« Validez-vous ce projet ? »** avec les cases **OUI** et **NON** ;
   - quand les trois valideurs internes ont validé, le même mail et la même
     page sont envoyés aux trois valideurs ITMAI ;
   - quand tout le monde a validé, le créateur reçoit un mail « Votre projet
     AVA est validé ».
   - Un refus marque immédiatement le projet comme refusé.
4. **Tableau de pilotage** : toutes les fiches projet en colonnes, avec pour
   chaque valideur l'état en couleur —
   - 🟢 **vert** : a validé ;
   - 🟠 **orange** : mail envoyé, en attente de validation ;
   - 🔴 **rouge** : a refusé ;
   - gris : mail non encore envoyé.
   Les dates de réponse sont affichées. Dernière colonne : **Archiver** ou
   **Supprimer**.
5. **Archives** : un projet archivé est retiré du tableau de pilotage et
   apparaît dans la table des archives (accessible depuis l'accueil). Il peut
   y être désarchivé ou supprimé définitivement.

## Envoi des mails

Le serveur SMTP se configure par variables d'environnement (voir
`.env.example`) : `AVA_SMTP_HOST`, `AVA_SMTP_PORT`, `AVA_SMTP_TLS`,
`AVA_SMTP_USER`, `AVA_SMTP_PASSWORD`, `AVA_SMTP_SENDER`.

Sans SMTP configuré, l'application n'échoue pas : les mails sont journalisés
et consultables pour chaque projet via le bouton **Mails** du tableau de
pilotage, ce qui permet de tester le workflow de bout en bout.

## Lancer l'application

### Sous Windows (le plus simple)

Double-cliquez sur **`demarrer.bat`** : il vérifie Python, installe les
composants au premier lancement, démarre l'application et ouvre automatiquement
le navigateur sur http://127.0.0.1:5000

### Manuellement (Windows, Mac, Linux)

```bash
pip install -r requirements.txt
python app.py
```

L'application est disponible sur http://127.0.0.1:5000
( variables : `AVA_PORT`, `AVA_DEBUG`, `AVA_SECRET_KEY`, `AVA_DB_PATH` ).

La base SQLite `ava.db` est créée automatiquement au premier démarrage.

Bonjour {{ validator.first_name }} {{ validator.last_name }},

Vous avez un projet AVA à valider.

Récapitulatif du projet :

- Nom du projet : {{ project.name }}
- Date : {{ project.date }}
- Responsable projet : {{ project.creator_name }} ({{ project.creator_email }})
- UP concernée : {{ project.up }}
- Délai de lancement cible : {{ project.launch_delay_months }} mois après validation définitive
- Gain total estimé : {{ project.total_gain }} €

Pour consulter le descriptif détaillé et valider le projet (OUI / NON), ouvrez
la page de validation suivante :

{{ link }}

Merci,

-- Application AVA

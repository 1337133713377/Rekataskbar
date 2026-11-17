# Nouveautés de REKA Taskbar

## 1.3.0

- Nouveau look du lecteur, en haut au milieu : l'icône de l'application qui joue (Spotify, Deezer, navigateur…), le nom du morceau et une vague d'audio qui danse au rythme de la musique.
- La vague suit le vrai niveau du canal « Musique » de REKA ; si ce canal reste muet pendant la lecture (musique routée ailleurs), elle s'anime toute seule. En pause, elle se pose.
- Clic : le lecteur complet ; clic du milieu : lecture / pause ; l'artiste est dans la bulle.
- L'ancien style (pochette, titre et artiste, boutons) reste disponible, tout comme le choix du canal suivi par la vague : Réglages → Widgets.

## 1.2.0

- Lecteur de musique au milieu de la barre : pochette, titre et artiste sur deux lignes, avancée du morceau. Un clic ouvre le lecteur complet : grande pochette, frise pour avancer ou reculer dans le morceau, précédent / pause / suivant, et un bouton pour afficher l'application qui joue. Sans musique, il reste discret (« Aucune lecture »), ou se cache (Réglages → Widgets).
- Jeux en plein écran : Ctrl+Alt+B fait revenir la barre par-dessus le jeu, le temps d'ouvrir une fenêtre ou une application ; elle repart toute seule (raccourci modifiable dans Réglages → Barre).
- Les fenêtres de la barre (réglages, mini-console, nouveautés) et les applications ouvertes depuis la barre passent devant le jeu au lieu de s'ouvrir derrière.
- Derrière un jeu, la barre ne se redessine plus et ne relève plus les fenêtres : rien de pris au jeu.
- Correction : la barre ne repasse plus devant le jeu quand il change la résolution de l'écran (plein écran exclusif), ce qui pouvait le faire sortir du plein écran.
- Correction : une fenêtre simplement agrandie n'est plus prise pour un plein écran (la barre disparaissait derrière un navigateur agrandi).
- Correction : la barre ne se remet plus « au-dessus de tout » chaque seconde, ce qui passait devant les incrustations de jeu et les autres fenêtres toujours visibles.
- Les applications réduites se rouvrent à coup sûr d'un clic, même quand Windows refusait de les ramener au premier plan.
- Le compteur « +3 » des fenêtres qui ne tiennent pas dans la barre s'ouvre d'un clic : la liste permet de les afficher (réduites comprises).

## 1.1.1

- Correction : la vérification du plein écran (Ctrl+Échap, passage derrière les jeux) plantait à chaque seconde sous Windows et ne faisait rien. Elle fonctionne maintenant.

## 1.1.0

- Mises à jour plus sûres : si une nouvelle version ne démarre pas, la barre revient toute seule à l'ancienne et ne réinstalle pas la version fautive.
- La progression du téléchargement s'affiche dans la barre ; un clic sur « prête » installe tout de suite.
- La barre n'installe plus de mise à jour pendant un jeu en plein écran : elle attend que tu en sortes.
- Vérification toutes les 3 heures, et nouvel essai après quelques minutes si le réseau manquait.
- Après une mise à jour, une bulle près de l'horloge annonce la version ; un clic montre les nouveautés (aussi dans le menu : « Nouveautés… »).
- Correction : la barre restait invisible après Ctrl+Échap pendant un jeu en plein écran.
- Mode compact pour second écran : barre fine avec les widgets essentiels (Réglages → Barre).

## 1.0.0

Première version : une barre des tâches pour Windows 10 / 11, reliée à REKA.

- Widgets REKA : bouton REKA (afficher ou lancer la console), canaux avec leurs niveaux, micro, casque et mini-console (faders, VU-mètres, Muet, envois), aux couleurs du thème de REKA.
- Widgets d'usage courant : Démarrer, raccourcis, fenêtres ouvertes, musique en cours, processeur et mémoire, réseau, météo, batterie, horloge et calendrier.
- Barre en haut ou en bas de l'écran, place réservée, passage derrière les jeux en plein écran, barre de Windows masquable.
- Raccourci clavier global pour couper le micro, démarrage avec Windows.
- Mises à jour automatiques : la barre télécharge, vérifie et installe les nouvelles versions toute seule.

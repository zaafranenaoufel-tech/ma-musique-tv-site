# Guide EPG GoldenOTT

Ce dossier publie un guide XMLTV ciblé pour la liste Xtream Codes « naoufel », à partir de grilles TV publiques datées.

- `mapping.json` : correspondances d'identifiants déjà présents dans l'export fourni.
- `scripts/build_epg.py` : fusion et transposition des programmes actuels.
- `guide.xml.gz` : publié uniquement lorsqu'au moins une grille contient des programmes récents.
- `status.json` : nombre de chaînes et de programmes effectivement présents.
- Actualisation prévue : 03h18 et 15h18 UTC.

Ce guide **ne modifie pas la playlist**, ne contient aucun mot de passe ou URL de streaming et **ne peut pas créer d'EPG réel sur une chaîne qui n'a pas de programmation publiée**. Les flux sans identifiant Xtream nécessitent encore une attribution dans l'application ou une correction chez le fournisseur.

Pour une source à ajouter dans GoldenOTT une fois la génération réussie :

`https://raw.githubusercontent.com/zaafranenaoufel-tech/ma-musique-tv-site/main/goldenott/guide.xml.gz`

Ne pas ajouter l'adresse avant la création effective du fichier.

# Phase 6 — snapshot + GitHub Pages

Prototype telephone : HTTPS obligatoire (audio + pad + WASM).

## 1. Extraire CE zip dans D:\PhenixRebirth-Mobile

Ecrase les fichiers listes. Ne touche PAS assets/ (OGG deja la).
Garde archives\repo\ si tu l as (wheel pygame_static).

## 2. Commit source (branche main-mobile)

```
cd D:\PhenixRebirth-Mobile
git add main.py VERSION PHASE6.md patch-index.ps1 lancer-web.bat publish-pages.bat src
git status
git commit -m "1.1.0-mobile.1: phase6 snapshot web tactile + pad"
git tag -a v1.1.0-mobile.1 -m "phase 6 snapshot"
git push -u origin main-mobile
git push origin v1.1.0-mobile.1
```

Ne commite PAS build\ ni __pycache__.

## 3. Pack web + push gh-pages

```
cd D:\PhenixRebirth-Mobile
.\publish-pages.bat
```

Le bat pack pygbag, patch index, ajoute .nojekyll, force-push
la branche gh-pages (contenu de build\web seulement).

## 4. Activer Pages sur GitHub

Repo PhenixRebirth-Mobile → Settings → Pages
- Source : Deploy from a branch
- Branch : gh-pages / root
Attendre 1 min.

URL :
https://kraran.github.io/PhenixRebirth-Mobile/

Telephone : paysage, Chrome, 1er tap = audio.
Manette BT : appuyer A une fois.

## Hors phase 6

APK Play Store = phase 7.

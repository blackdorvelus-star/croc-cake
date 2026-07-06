# Croc Cake

Site web de **Croc Cake inc.** — gâteaux, mini-muffins et gâteries pour chiens
confectionnés au Québec, en vente dans une centaine d'animaleries partenaires.

Site statique construit avec [Astro](https://astro.build/) et
[Tailwind CSS](https://tailwindcss.com/). Destiné à `croccake.com`.

## Développement

```bash
npm install
npm run dev      # serveur local http://localhost:4321
npm run build    # génère le site statique dans dist/
npm run preview  # prévisualise le build
```

## Structure

| Chemin | Rôle |
| --- | --- |
| `src/pages/` | Pages du site (Astro) |
| `src/components/` | En-tête, pied de page, localisateur d'animaleries |
| `src/layouts/Base.astro` | Gabarit commun (SEO, Open Graph, JSON-LD) |
| `src/data/site.ts` | Coordonnées de l'entreprise — **source unique de vérité** |
| `src/data/stores.json` | Boutiques géocodées (localisateur) |
| `src/data/pending-stores.json` | Boutiques listées par région, sans géocodage |
| `src/assets/photos/` | Photos (optimisées automatiquement au build) |

## Points de configuration

- **Coordonnées, réseaux sociaux, téléphone** : `src/data/site.ts`.
- **Portail partenaires** : `PARTNER_PORTAL_URL` dans `src/data/site.ts`. Tant
  qu'il est vide, la page *Animaleries* propose un bouton courriel pré-rempli
  vers `info@croccake.com` ; dès qu'une URL y est inscrite, le bouton pointe
  vers le site dédié aux animaleries.
- **Formulaire de contact** : compose un courriel pré-rempli vers
  `info@croccake.com` (aucun service tiers requis).
- **Photos des testeurs** (page *Notre histoire*) : déposer les images dans
  `src/assets/photos/testeurs/` (voir le fichier `LISEZMOI.txt` du dossier).

## Prévisualisation en ligne

Le workflow `.github/workflows/deploy-pages.yml` publie automatiquement une
prévisualisation sur GitHub Pages à chaque push sur `main` :

**https://blackdorvelus-star.github.io/croc-cake/**

Comme Pages sert le site sous le sous-chemin `/croc-cake/` (alors que la
production vise `croccake.com`), `scripts/rewrite-base.mjs` réécrit les URL
racine-relatives **après le build**, sans toucher au code source.

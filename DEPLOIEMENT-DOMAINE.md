# Brancher croccake.com sur le nouveau site

Ce document explique comment faire pointer le domaine `croccake.com`
(actuellement chez VotreSite.ca, sur l'ancien site owebo) vers le nouveau
site. Le domaine et les courriels (`info@croccake.com`) **restent chez
VotreSite.ca** — on ne modifie qu'un seul réglage technique.

## État actuel du domaine (relevé DNS)

| Type | Valeur actuelle | À faire |
| --- | --- | --- |
| **A** (site web, `@`) | `192.34.93.147` | 🔁 **À remplacer** par les 4 adresses GitHub ci-dessous |
| **MX** (courriel) | `smtp1.croccake.com`, `smtp2.croccake.com` | ✅ Ne pas toucher |
| **TXT** (SPF, anti-pourriel) | `v=spf1 include:zcsend.net include:spf.votresite.ca ~all` | ✅ Ne pas toucher |
| **CNAME** `www` | pointe vers `croccake.com` | ✅ Ne pas toucher (suivra automatiquement le A) |
| **NS** (serveurs de noms) | `ns1.croccake.com`, `ns2.croccake.com` (VotreSite) | ✅ Ne pas toucher |

## Étape 1 — Modifier l'enregistrement A chez VotreSite.ca

Dans l'espace client VotreSite.ca, section **Nom de domaine → DNS** (ou
**Zone DNS**), remplacer l'enregistrement **A** du domaine racine (`@` ou
`croccake.com`) par les **4 adresses IP officielles de GitHub Pages** :

```
185.199.108.153
185.199.109.153
185.199.110.153
185.199.111.153
```

(Certains panneaux demandent 4 lignes séparées — c'est normal, GitHub
répartit la charge sur ces 4 adresses.)

Si le panneau propose aussi des enregistrements **AAAA** (IPv6, facultatif) :

```
2606:50c0:8000::153
2606:50c0:8001::153
2606:50c0:8002::153
2606:50c0:8003::153
```

Ne rien changer d'autre — surtout pas le MX ni le TXT/SPF, sinon les
courriels `info@croccake.com` risquent de cesser de fonctionner.

## Étape 2 — Déclencher la mise en production

Une fois le changement fait chez VotreSite (la propagation prend de
quelques minutes à quelques heures), lancer le workflow **« Mise en
production (domaine croccake.com) »** :

GitHub → onglet **Actions** → *Mise en production (domaine croccake.com)*
→ **Run workflow**.

⚠️ Ce workflow doit être déclenché **seulement après** le changement DNS —
il configure `croccake.com` comme domaine officiel du site, ce qui fait
rediriger l'ancien lien de démo (`blackdorvelus-star.github.io/croc-cake/`)
vers `croccake.com`. Si le DNS n'est pas encore basculé à ce moment-là, le
lien de démo affichera temporairement l'ancien site owebo.

## Étape 3 — Vérifier

- `https://croccake.com` doit afficher le nouveau site (peut prendre
  jusqu'à 24 h pour une propagation complète, mais généralement moins
  d'une heure).
- Le cadenas HTTPS se met en place automatiquement (certificat gratuit
  géré par GitHub), généralement en quelques minutes après la propagation
  du DNS.
- Envoyer un courriel test à `info@croccake.com` pour confirmer que la
  boîte fonctionne toujours.

## Retour en arrière si besoin

Remettre l'enregistrement A à sa valeur d'origine (`192.34.93.147`) chez
VotreSite.ca. L'ancien site owebo n'a pas été touché ni supprimé — tant que
l'abonnement VotreSite reste actif, il redevient accessible dès que le DNS
est remis comme avant.

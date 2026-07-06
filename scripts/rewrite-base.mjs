/**
 * Réécrit les URL racine-relatives du dossier `dist/` pour un hébergement
 * sous un sous-chemin (GitHub Pages : /croc-cake/). Ne touche PAS au code
 * source : c'est une étape post-build propre au déploiement de prévisualisation.
 * Les URL absolues (https://croccake.com…) restent intactes.
 */
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { join, extname } from 'node:path';

const DIST = new URL('../dist/', import.meta.url).pathname;
const BASE = process.env.PREVIEW_BASE || '/croc-cake';

async function walk(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walk(p)));
    else out.push(p);
  }
  return out;
}

function rewriteHtml(html) {
  return html
    // href="/…" et src="/…" (mais pas //… ni déjà basé)
    .replace(/\b(href|src)="\/(?!\/)/g, `$1="${BASE}/`)
    // srcset : chaque candidat commençant par /
    .replace(/\bsrcset="([^"]*)"/g, (_m, v) =>
      `srcset="${v.replace(/(^|,\s*)\/(?!\/)/g, `$1${BASE}/`)}"`)
    // url(/…) dans les styles inline
    .replace(/url\(\/(?!\/)/g, `url(${BASE}/`);
}

function rewriteJs(js) {
  // Chemins fetch() absolus vers les données statiques
  return js
    .replace(/(["'`])\/data\//g, `$1${BASE}/data/`)
    .replace(/(["'`])\/_astro\//g, `$1${BASE}/_astro/`);
}

function rewriteCss(css) {
  // url(/_astro/…) — polices et assets référencés depuis les feuilles de style
  return css.replace(/url\(\/(?!\/)/g, `url(${BASE}/`);
}

const files = await walk(DIST);
let htmlCount = 0, jsCount = 0, cssCount = 0;
for (const f of files) {
  const ext = extname(f);
  if (ext === '.html') {
    await writeFile(f, rewriteHtml(await readFile(f, 'utf8')));
    htmlCount++;
  } else if (ext === '.js') {
    await writeFile(f, rewriteJs(await readFile(f, 'utf8')));
    jsCount++;
  } else if (ext === '.css') {
    await writeFile(f, rewriteCss(await readFile(f, 'utf8')));
    cssCount++;
  }
}
console.log(`Réécriture base "${BASE}" : ${htmlCount} HTML, ${jsCount} JS, ${cssCount} CSS.`);

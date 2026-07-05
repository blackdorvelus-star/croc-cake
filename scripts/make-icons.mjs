// Génère favicon, apple-touch-icon et image Open Graph à partir du logo et d'une photo produit réelle.
import sharp from 'sharp';
import { mkdir } from 'node:fs/promises';

const LOGO = 'src/assets/logo-croc-cake.png';
const BEIGE = { r: 249, g: 242, b: 231, alpha: 1 }; // beige-100

await mkdir('public', { recursive: true });

// Favicon 64x64 (logo sur fond transparent)
await sharp(LOGO).resize(64, 64, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toFile('public/favicon.png');

// Apple touch icon 180x180 sur fond beige
await sharp(LOGO)
  .resize(150, 150, { fit: 'contain', background: BEIGE })
  .extend({ top: 15, bottom: 15, left: 15, right: 15, background: BEIGE })
  .flatten({ background: BEIGE })
  .png()
  .toFile('public/apple-touch-icon.png');

// Image Open Graph 1200x630 : photo réelle du gâteau rose + logo
const photo = await sharp('source-content/images/IMG_20250227_181206_crop_3.JPG')
  .resize(1200, 630, { fit: 'cover', position: 'centre' })
  .toBuffer();
const logoSmall = await sharp(LOGO)
  .resize(180, 180, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
  .png()
  .toBuffer();
await sharp(photo)
  .composite([{ input: logoSmall, top: 30, left: 30 }])
  .jpeg({ quality: 85 })
  .toFile('public/og-croc-cake.jpg');

console.log('Icônes et image OG générées.');

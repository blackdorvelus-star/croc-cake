/** Informations réelles de l'entreprise — source unique de vérité. */
export const SITE = {
  name: 'Croc Cake inc.',
  shortName: 'Croc Cake',
  url: 'https://croccake.com',
  slogan: 'Pour des moments festifs avec vos animours !',
  description:
    'Croc Cake inc. confectionne à Laval des gâteaux, mini-muffins et gâteries pour chiens, faits d’ingrédients choisis pour eux. En vente dans une centaine d’animaleries partenaires partout au Québec.',
  phone: '514-265-2824',
  phoneHref: '+15142652824',
  email: 'info@croccake.com',
  address: {
    locality: 'Laval',
    region: 'QC',
    country: 'CA',
  },
  social: {
    facebook: 'https://www.facebook.com/croccake',
    instagram: 'https://www.instagram.com/croccakeinc',
  },
  founder: 'Anie Grondin',
  priceRange: '17,99 $ – 19,99 $',
} as const;

/**
 * Clé d'accès Web3Forms (service gratuit qui achemine les formulaires vers
 * info@croccake.com). Pour l'obtenir : https://web3forms.com → entrer
 * info@croccake.com → la clé arrive par courriel. Remplacer la valeur ci-dessous.
 */
export const WEB3FORMS_KEY = 'REMPLACEZ_PAR_VOTRE_CLE_WEB3FORMS';

export const NAV = [
  { href: '/', label: 'Accueil' },
  { href: '/produits', label: 'Nos produits' },
  { href: '/points-de-vente', label: 'Points de vente' },
  { href: '/notre-histoire', label: 'Notre histoire' },
  { href: '/galerie', label: 'Galerie' },
  { href: '/faq', label: 'FAQ' },
  { href: '/contact', label: 'Contact' },
] as const;

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
 * URL du futur site dédié aux demandes de partenariat des animaleries.
 * Tant qu'elle est vide, la page /animaleries affiche un bouton de courriel
 * pré-rempli vers info@croccake.com ; dès qu'elle est renseignée, le bouton
 * pointe vers ce site.
 */
export const PARTNER_PORTAL_URL = '';

export const NAV = [
  { href: '/', label: 'Accueil' },
  { href: '/produits', label: 'Nos produits' },
  { href: '/points-de-vente', label: 'Points de vente' },
  { href: '/notre-histoire', label: 'Notre histoire' },
  { href: '/galerie', label: 'Galerie' },
  { href: '/faq', label: 'FAQ' },
  { href: '/contact', label: 'Contact' },
] as const;

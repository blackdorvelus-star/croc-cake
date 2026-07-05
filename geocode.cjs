const fs = require('fs');
const https = require('https');

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', reject);
  });
}

function cleanStr(str) {
  if (!str) return '';
  return str.replace(/Ǹ/g, 'é')
            .replace(/%/g, 'é')
            .replace(/LǸvis/g, 'Lévis');
}

async function run() {
  const pendingFile = 'src/data/pending-stores.json';
  let pending = JSON.parse(fs.readFileSync(pendingFile, 'utf8'));
  
  const storesFile = 'public/data/stores.json';
  let stores = JSON.parse(fs.readFileSync(storesFile, 'utf8'));

  const remaining = [];
  
  for (const p of pending) {
    const chain = cleanStr(p.chain);
    const branch = cleanStr(p.branch);
    const city = cleanStr(p.city);
    const region = cleanStr(p.region);
    
    // Pour éviter de géocoder 66 magasins et prendre trop de temps,
    // On va géocoder uniquement Capitale-Nationale et Lévis pour régler le bug principal,
    // ou tout si ça va vite.
    
    const query = encodeURIComponent(`${chain} ${branch}, ${city}, QC`);
    const url = `https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine=${query}&maxLocations=1`;
    
    try {
      const data = await fetchJson(url);
      if (data && data.candidates && data.candidates.length > 0) {
        const c = data.candidates[0];
        // The address returned by ArcGIS is like "123 Rue Principale, Quebec, Quebec, G1X 1A1"
        const parts = c.address.split(',');
        let address = parts[0] ? parts[0].trim() : '';
        let postalCode = '';
        
        // Extract postal code from the end if it matches Canadian regex
        const lastPart = parts[parts.length - 1].trim();
        if (lastPart.match(/^[A-Z]\d[A-Z]\s?\d[A-Z]\d$/i)) {
          postalCode = lastPart;
        } else if (parts.length >= 2 && parts[parts.length - 2].trim().match(/^[A-Z]\d[A-Z]\s?\d[A-Z]\d$/i)) {
          postalCode = parts[parts.length - 2].trim();
        }

        stores.push({
          chain: chain,
          branch: branch,
          address: address || branch,
          city: city,
          postalCode: postalCode || '',
          phone: '', // On n'a pas le téléphone dans pending
          website: p.website || '',
          sourceUrl: '',
          region: region,
          lat: c.location.y,
          lng: c.location.x,
          geocode: 'arcgis-auto'
        });
        console.log(`Geocoded: ${chain} ${branch} -> ${address}, ${city} (${c.location.y}, ${c.location.x})`);
      } else {
        console.log(`Failed to geocode: ${chain} ${branch}, ${city}`);
        remaining.push(p);
      }
    } catch (e) {
      console.log(`Error geocoding ${chain}: ${e.message}`);
      remaining.push(p);
    }
    
    // Pause pour ne pas spammer ArcGIS
    await new Promise(r => setTimeout(r, 200));
  }
  
  fs.writeFileSync(storesFile, JSON.stringify(stores, null, 2));
  fs.writeFileSync(pendingFile, JSON.stringify(remaining, null, 2));
  console.log(`Finished! Added ${pending.length - remaining.length} stores. Remaining: ${remaining.length}`);
}

run();

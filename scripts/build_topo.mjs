// Writes docs/data/<layer>.topo.json from each boundary layer's GeoJSON in docs/data/,
// then proves the conversion changed no lookups that matter.
//
// TopoJSON stores each shared border once and quantizes coordinates to a grid
// (1e5 steps across the layer's extent, about half a meter in New York City),
// which cuts the boundary download roughly in half. The site loads only the
// .topo.json files; the GeoJSON stays as the pipeline's working copy and is what
// validate_lookups.py checks against live city records.
//
// The check: 6,000 random points per layer are looked up in both versions with the
// site's own point-in-polygon test. A disagreement is allowed only when the point
// sits within 1 meter of a boundary in the original (closer than the 2 meter
// simplification already blurs it). Anything else fails the build.
//
// Run from the repo root:  node scripts/build_topo.mjs
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';

const DIR = 'docs/data';
const LAYERS = ['nta','cd','council','precinct','schooldist','eszones','mszones','dsny','congress',
  'assembly','senate','hurricane','historic','elections','tracts','hoods_alt','hoods_whong'];
const QUANT = '1e5', SAMPLES = 6000, TOLERANCE_M = 1;

// --- the same decoder and point-in-polygon test the page uses ---
function topoToGeo(t){
  const [sx, sy] = t.transform.scale, [tx, ty] = t.transform.translate;
  const arcs = t.arcs.map(arc => { let x = 0, y = 0; return arc.map(([dx, dy]) => [(x += dx) * sx + tx, (y += dy) * sy + ty]); });
  const ring = ids => { const pts = []; ids.forEach((i, k) => { const a = i < 0 ? arcs[~i].slice().reverse() : arcs[i]; (k ? a.slice(1) : a).forEach(p => pts.push(p)); }); return pts; };
  const geom = g => g.type === 'Polygon' ? {type:'Polygon', coordinates:g.arcs.map(ring)}
    : g.type === 'MultiPolygon' ? {type:'MultiPolygon', coordinates:g.arcs.map(p => p.map(ring))} : null;
  const obj = t.objects[Object.keys(t.objects)[0]];
  return {type:'FeatureCollection', features: obj.geometries.map(g => ({type:'Feature', properties:g.properties || {}, geometry:geom(g)}))};
}
function ringContains(r,x,y){let c=false;for(let i=0,j=r.length-1;i<r.length;j=i++){const xi=r[i][0],yi=r[i][1],xj=r[j][0],yj=r[j][1];if(((yi>y)!==(yj>y))&&(x<(xj-xi)*(y-yi)/(yj-yi)+xi))c=!c;}return c;}
function polyContains(p,x,y){if(!ringContains(p[0],x,y))return false;for(let k=1;k<p.length;k++)if(ringContains(p[k],x,y))return false;return true;}
const polys = g => !g ? [] : g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
function bbox(g){let a=180,b=90,c=-180,d=-90;polys(g).forEach(p=>p.forEach(r=>r.forEach(([x,y])=>{if(x<a)a=x;if(x>c)c=x;if(y<b)b=y;if(y>d)d=y;})));return[a,b,c,d];}
function index(fc){fc.features.forEach(f=>f._bb=f.geometry?bbox(f.geometry):[1,1,-1,-1]);return fc;}
function lookup(fc,lat,lng){for(const f of fc.features){const b=f._bb;if(lng<b[0]||lng>b[2]||lat<b[1]||lat>b[3])continue;if(polys(f.geometry).some(p=>polyContains(p,lng,lat)))return f;}return null;}
function metersToEdge(fc, lat, lng){
  const kx = Math.cos(lat*Math.PI/180)*111320, ky = 111320;
  let best = Infinity;
  for (const f of fc.features) for (const p of polys(f.geometry)) for (const r of p) for (let i = 1; i < r.length; i++){
    const ax=(r[i-1][0]-lng)*kx, ay=(r[i-1][1]-lat)*ky, bx=(r[i][0]-lng)*kx, by=(r[i][1]-lat)*ky;
    const dx=bx-ax, dy=by-ay, t=Math.max(0,Math.min(1,-(ax*dx+ay*dy)/((dx*dx+dy*dy)||1)));
    best = Math.min(best, Math.hypot(ax+t*dx, ay+t*dy));
  }
  return best;
}

let seed = 7; const rnd = () => (seed = (seed*16807) % 2147483647) / 2147483647;
const pts = Array.from({length:SAMPLES}, () => [40.49 + rnd()*0.43, -74.26 + rnd()*0.58]);
let failed = false, rawTotal = 0, topoTotal = 0;
for (const L of LAYERS){
  const src = `${DIR}/${L}.json`, out = `${DIR}/${L}.topo.json`;
  execFileSync('npx', ['-y', 'mapshaper', src, '-o', 'force', 'format=topojson', `quantization=${QUANT}`, out], {stdio:'pipe'});
  const geo = index(JSON.parse(fs.readFileSync(src))), topo = index(topoToGeo(JSON.parse(fs.readFileSync(out))));
  const k = f => JSON.stringify(f?.properties ?? null);
  const problems = [];
  if (geo.features.length !== topo.features.length) problems.push(`feature count ${geo.features.length} -> ${topo.features.length}`);
  if (!geo.features.every((f,i) => k(f) === k(topo.features[i]))) problems.push('properties differ');
  let edge = 0;
  for (const [lat,lng] of pts){
    if (k(lookup(geo,lat,lng)) === k(lookup(topo,lat,lng))) continue;
    const d = metersToEdge(geo, lat, lng);
    if (d <= TOLERANCE_M) edge++;
    else problems.push(`${lat.toFixed(6)},${lng.toFixed(6)} differs ${d.toFixed(2)} m from any boundary`);
  }
  rawTotal += fs.statSync(src).size; topoTotal += fs.statSync(out).size;
  console.log(`${L.padEnd(12)} ${problems.length ? 'FAIL' : 'ok  '} ${edge} boundary-line disagreements in ${SAMPLES}${problems.length ? '\n  ' + problems.join('\n  ') : ''}`);
  if (problems.length) failed = true;
}
console.log(`GeoJSON ${(rawTotal/1e6).toFixed(1)} MB -> TopoJSON ${(topoTotal/1e6).toFixed(1)} MB (uncompressed)`);
if (failed){ console.error('TopoJSON check failed — do not deploy.'); process.exit(1); }

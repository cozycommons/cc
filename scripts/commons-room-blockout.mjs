import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateSync } from 'node:zlib';
import { randomUUID } from 'node:crypto';

// Prototype authoring export; never reads or modifies the persistent scene.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'art/commons/commons-room-blockout.bbmodel');
if (fs.existsSync(output) && !process.argv.includes('--replace-generated')) {
  throw new Error('Output exists. Use --replace-generated only to discard edits to this generated model.');
}
function crc(data) {
  let c = 0xffffffff;
  for (const byte of data) { c ^= byte; for (let n = 0; n < 8; n++) c = (c >>> 1) ^ ((c & 1) ? 0xedb88320 : 0); }
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const t = Buffer.from(type), size = Buffer.alloc(4), checksum = Buffer.alloc(4);
  size.writeUInt32BE(data.length); checksum.writeUInt32BE(crc(Buffer.concat([t, data])));
  return Buffer.concat([size, t, data, checksum]);
}
function texture(name, hex) {
  const rgb = hex.match(/../g).map(v => parseInt(v, 16));
  const raw = Buffer.alloc(16 * 49);
  for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) {
    const variation = ((x * 13 + y * 7) % 7) - 3;
    rgb.forEach((v, i) => { raw[y * 49 + 1 + x * 3 + i] = Math.max(0, Math.min(255, v + variation)); });
  }
  const header = Buffer.alloc(13); header.writeUInt32BE(16); header.writeUInt32BE(16, 4); header[8] = 8; header[9] = 2;
  const png = Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), chunk('IHDR', header), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
  return {name, uuid: randomUUID(), source: `data:image/png;base64,${png.toString('base64')}`, mode: 'bitmap', saved: false, internal: true, uv_width: 16, uv_height: 16, width: 16, height: 16};
}
const palette = {wood:'885334', plank:'a66b40', dark:'392c35', plaster:'b58a60', orange:'bd592b', cushion:'d57637', gold:'e8b653', olive:'697044', cream:'ead1a1', night:'30314f', glass:'515574', metal:'47434a', tile:'c8a881', rug:'713744', leaf:'506039', shadow:'251f2a', clay:'9f4d35'};
const textures = Object.entries(palette).map(([n, c]) => texture(n, c));
const indices = Object.keys(palette);
const elements = [], groups = [], outliner = [];
let current;
function group(name, origin = [0,0,0]) { const uuid = randomUUID(); groups.push({name, uuid, origin, rotation:[0,0,0], export:true, visibility:true}); current = {uuid,isOpen:false,children:[]}; outliner.push(current); }
function box(name, from, to, material, transform = {}) {
  const uuid = randomUUID();
  const faces = Object.fromEntries(['north','east','south','west','up','down'].map(f => [f,{uv:[0,0,16,16],texture:indices.indexOf(material)}]));
  const origin = transform.origin || from.map((value, index) => (value + to[index]) / 2);
  elements.push({name,uuid,type:'cube',from,to,origin,rotation:transform.rotation || [0,0,0],box_uv:false,faces,visibility:true,export:true}); current.children.push(uuid);
}
group('01 Shell · floor and cutaway walls');
box('Foundation',[-64,-5,-56],[64,0,56],'dark');
for(let z=-56;z<56;z+=8) for(let x=-64;x<64;x+=32) box('Timber floor plank',[x+.2,0,z+.2],[x+31.8,.8,z+7.8],((x+z)%3)?'wood':'plank');
box('Back plaster',[-64,0,-58],[64,56,-56],'plaster');
box('Left wall lower',[-66,0,-56],[-64,12,56],'plaster');
box('Left wall upper',[-66,48,-56],[-64,56,56],'plaster');
for(const z of [-56,-10,38,54]) box('Window pier',[-66,12,z],[-64,48,z+2],'plaster');
box('Back crown',[-66,54,-59],[66,58,-55],'dark');
box('Left crown',[-67,54,-56],[-63,58,58],'dark');
box('Back skirting',[-64,1,-56],[64,3,-54],'wood');
box('Commons banner',[-38,34,-55.8],[-10,49,-55.1],'rug');
box('Banner inner field',[-35,37,-55],[-13,46,-54.7],'night');
for(const x of [-31,-24,-17]) box('Banner stitch',[x,39,-54.5],[x+2,44,-54.2],'gold');
for(const x of [-31,-22]) {
  box('Pendant cord',[x,37,-32],[x+0.5,53,-31.5],'dark');
  box('Pendant shade',[x-3,33,-35],[x+3.5,38,-29],'gold');
  box('Pendant glow',[x-1.5,31,-33.5],[x+2,34,-30.5],'cream');
}
group('02 Windows · blue night glazing');
for(const z of [-54,-8]) {
  box('Night glass',[-65,12,z],[-64.5,48,z+44],'night');
  for(const zz of [z,z+22,z+44]) box('Vertical window frame',[-64.5,12,zz],[-63,48,zz+1],'dark');
  box('Crossbar',[-64.5,29,z],[-63,30,z+44],'wood');
  box('Window sill',[-66,11,z],[-61,13,z+44],'wood');
  for(let n=0;n<5;n++) box('Distant lit window',[-64.4,16+(n%3)*8,z+4+n*7],[-64.2,19+(n%3)*8,z+6+n*7],n%2?'glass':'gold');
}
group('03 Kitchen · fixed cabinetry');
for(let x=0;x<60;x+=20) {
  box('Base cabinet',[x,1,-55],[x+19,17,-42],'dark');
  box('Oak worktop',[x-.5,17,-55.5],[x+19.5,19,-41],'wood');
  box('Door pull',[x+7,13,-41.8],[x+12,14,-41.2],'gold');
}
for(let x=0;x<60;x+=6) for(let y=20;y<32;y+=6) box('Backsplash tile',[x,y,-55.8],[x+5.7,y+5.7,-55.1],'tile');
box('Hob',[20,19,-53],[37,19.8,-43],'metal');
for(const x of [23,31]) box('Burner',[x,19.8,-51],[x+4,20,-47],'dark');
box('Sink',[43,19,-53],[56,19.5,-44],'metal');
for(const y of [34,46]) box('Open oak shelf',[4,y,-56],[56,y+1.5,-48],'wood');
for(const x of [5,55]) box('Shelf upright',[x,34,-56],[x+1.5,48,-48],'dark');
box('Tall pantry',[-19,1,-55],[-2,48,-43],'dark');
box('Pantry inset',[-17,4,-42.9],[-4,45,-42.2],'night');
for(const y of [17,32]) box('Pantry divider',[-18,y,-42.1],[-3,y+1,-41.7],'wood');
group('04 Orange sofa · movable',[0,1,-18]);
box('Sofa plinth',[-22,3,-28],[22,7,-9],'wood');
box('Sofa back',[-23,7,-29],[23,23,-25],'orange');
for(const x of [-23,19]) box('Sofa arm',[x,7,-25],[x+4,16,-8],'orange');
for(const x of [-18,-6,6]) { box('Seat cushion',[x,7,-24],[x+11.5,11,-9],'cushion'); box('Back cushion',[x,11,-25],[x+11.5,21,-22],'orange'); }
for(const x of [-18,-6,6,18]) box('Sofa seam',[x,10.8,-23.5],[x+.5,11.2,-9.5],'dark');
box('Ochre throw',[-3,11,-23],[4,11.5,-8],'gold');
box('Throw over back',[-3,21,-26],[4,22,-22],'gold');
box('Left throw pillow',[-17,11,-23],[-9,18,-16],'cream',{rotation:[0,0,-8]});
box('Right throw pillow',[9,11,-23],[17,18,-16],'rug',{rotation:[0,0,8]});
for(const x of [-19,17]) for(const z of [-25,-12]) box('Sofa foot',[x,1,z],[x+2,4,z+2],'dark');
group('05 Rug · floor layer',[0,1,0]); box('Wine rug',[-25,1,-8],[25,1.2,18],'rug');
for(const z of [-7,16]) box('Rug border',[-24,1.2,z],[24,1.3,z+1],'gold');
for(const x of [-18,-9,0,9,18]) box('Rug motif',[x,1.25,-2],[x+4,1.35,12],x%2?'gold':'cream',{rotation:[0,18,0]});
for(let x=-23;x<24;x+=4) {
  box('Front fringe',[x,1.1,18],[x+2,1.25,20],'cream');
  box('Back fringe',[x,1.1,-10],[x+2,1.25,-8],'cream');
}
group('06 Coffee table · movable',[0,1,5]);
box('Table top',[-11,10,-2],[11,12,12],'wood');
box('Coffee table lower shelf',[-9,4,0],[9,6,10],'plank');
for(const x of [-9,7]) for(const z of [0,9]) box('Coffee table leg',[x,1,z],[x+2,10,z+2],'dark');
group('07 Dining table · movable',[0,1,37]);
box('Dining tabletop',[-24,18,27],[18,20,45],'plank');
box('Dining runner',[-20,20,34],[14,20.4,38],'rug');
for(const x of [-21,13]) for(const z of [29,41]) box('Dining leg',[x,1,z],[x+3,18,z+3],'wood');
group('08 Dining chair · movable',[-4,1,50]);
box('Chair seat',[-10,10,47],[2,12,57],'wood');
box('Chair back',[-10,12,56],[2,27,58],'wood');
for(const x of [-9,0]) for(const z of [48,55]) box('Chair leg',[x,1,z],[x+2,10,z+2],'dark');
group('09 Floor lamp · movable',[29,1,-22]);
box('Lamp base',[25,1,-26],[33,3,-18],'dark'); box('Lamp stem',[28,3,-23],[30,29,-21],'wood');
box('Shade lower',[23,28,-28],[35,31,-16],'gold');box('Shade upper',[25,31,-26],[33,37,-18],'cream');
group('10 Record cabinet · movable',[-51,1,4]);
box('Record cabinet',[-61,1,-12],[-43,15,20],'wood');
box('Record cabinet top',[-62,15,-13],[-42,17,21],'plank');
for(const z of [-9,8]) box('Speaker grille',[-61.8,4,z],[-61.2,13,z+9],'night');
for(let z=-10;z<19;z+=3) box('Record spine',[-42.9,3,z],[-42.5,13,z+2],z%2?'dark':'cream');
for(const z of [-8,8]) box('Turntable',[-59,17,z],[-46,18,z+10],'dark');
group('11 Olive loveseat · movable',[43,1,31]);
box('Loveseat base',[30,3,20],[56,8,40],'olive');box('Loveseat back',[30,8,37],[56,22,41],'olive');
for(const x of [30,53]) box('Loveseat arm',[x,8,20],[x+3,15,37],'olive');
for(const x of [34,44]) box('Loveseat cushion',[x,8,21],[x+9,11,36],'olive');
box('Loveseat pillow',[34,11,31],[42,18,38],'gold',{rotation:[0,0,-7]});
group('12 Plant · silhouette example',[52,1,9]);
box('Terracotta pot',[47,1,4],[57,9,14],'orange');box('Trunk',[51,9,8],[53,23,10],'wood');
for(const [x,y,z,r] of [[44,17,6,-18],[52,21,7,15],[47,26,8,-8]]) box('Leaf cluster',[x,y,z],[x+9,y+6,z+5],'leaf',{rotation:[0,0,r]});
group('13 Kitchen island · movable',[40,1,-19]);
box('Island cabinet',[31,1,-27],[50,16,-12],'dark');
box('Island end panel',[29,1,-29],[32,18,-10],'wood');
box('Island worktop',[28,17,-30],[53,20,-9],'plank');
box('Island shelf',[34,7,-11],[49,9,-9],'wood');
group('14 Dining bench · movable',[-35,1,37]);
box('Bench seat',[-54,10,27],[-28,13,37],'plank');
for(const x of [-51,-33]) box('Bench leg',[x,1,29],[x+3,10,35],'dark');
group('15 Bookcase · movable',[58,1,-30]);
for(const x of [53,61]) box('Bookcase side',[x,1,-39],[x+3,39,-23],'wood');
for(const y of [1,13,25,37]) box('Bookcase shelf',[53,y,-39],[64,y+2,-23],'plank');
for(const [y,z,m] of [[4,-37,'rug'],[4,-31,'cream'],[16,-37,'gold'],[16,-30,'olive'],[28,-36,'night'],[28,-29,'clay']]) box('Book block',[56,y,z],[61,y+8,z+4],m);
group('16 Sofa side table · movable',[-29,1,-14]);
box('Side table top',[-35,12,-20],[-25,15,-10],'plank');
box('Side table pedestal',[-31,3,-16],[-29,12,-14],'dark');
box('Side table foot',[-34,1,-19],[-26,3,-11],'dark');
group('17 Low storage chest · movable',[-47,1,42]);
box('Storage chest',[-60,1,35],[-42,13,49],'wood');
box('Storage chest lid',[-61,13,35],[-41,16,50],'plank');
box('Chest inset',[-56,5,49],[-46,10,50.5],'dark');
group('18 Tall planter · movable',[60,1,42]);
box('Large clay planter',[54,1,36],[64,12,47],'clay');
box('Tall trunk',[58,12,40],[60,34,43],'wood');
for(const [x,y,z,r] of [[51,22,38,-22],[57,27,36,18],[54,33,40,-10]]) box('Broad leaf',[x,y,z],[x+10,y+7,z+6],'leaf',{rotation:[0,0,r]});
const model = {meta:{format_version:'5.0',model_format:'free',box_uv:false},name:'Commons Room Blockout',resolution:{width:16,height:16},elements,groups,outliner,textures};
fs.mkdirSync(path.dirname(output),{recursive:true}); fs.writeFileSync(output,JSON.stringify(model,null,2));
console.log(`Saved ${output}: ${elements.length} cubes, ${groups.length} editable groups`);

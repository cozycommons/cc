import { AmbientLight, Box3, Color, DirectionalLight, PerspectiveCamera, Scene, Vector3, WebGLRenderer } from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { parseScanArchive } from './usdzArchive';

export async function mountScan(container, bytes, onError) {
  const model = await parseScanArchive(bytes);
  let vertices = 0;
  model.traverse((object) => { vertices += object.geometry?.attributes?.position?.count || 0; });
  if (vertices > 5_000_000) { disposeModel(model); throw new Error('This scan is too complex for the browser viewer. Export a smaller scan.'); }
  const bounds = new Box3().setFromObject(model);
  if (bounds.isEmpty() || ![...bounds.min.toArray(), ...bounds.max.toArray()].every(Number.isFinite)) {
    disposeModel(model);
    throw new Error('This scan contains no viewable geometry.');
  }
  const scene = new Scene();
  scene.background = new Color('#f5f3ed');
  scene.add(model, new AmbientLight(0xffffff, 2));
  const light = new DirectionalLight(0xffffff, 3);
  light.position.set(3, 8, 5);
  scene.add(light);
  let renderer;
  try { renderer = new WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true }); }
  catch { disposeModel(model); throw new Error('3D viewing requires WebGL. Try another browser or enable hardware acceleration.'); }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.appendChild(renderer.domElement);
  const camera = new PerspectiveCamera(45, 1, 0.01, 1000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.listenToKeyEvents(container);
  const center = bounds.getCenter(new Vector3());
  const span = Math.max(bounds.getSize(new Vector3()).length(), 0.01);
  const fit = () => {
    const distance = span / (2 * Math.tan(camera.fov * Math.PI / 360) * Math.min(1, camera.aspect));
    camera.position.copy(center).add(new Vector3(1, 0.75, 1).normalize().multiplyScalar(distance * 1.3));
    camera.near = span / 1000;
    camera.far = span * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.minDistance = span / 100;
    controls.maxDistance = span * 20;
    controls.update();
  };
  const resize = () => {
    const width = Math.max(container.clientWidth, 1), height = Math.max(container.clientHeight, 1);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  };
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  resize(); fit();
  const lostContext = (event) => { event.preventDefault(); onError(new Error('The 3D view stopped. Retry to reload the scan.')); };
  renderer.domElement.addEventListener('webglcontextlost', lostContext);
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  let disposed = false;
  return {
    fit,
    dispose() {
      if (disposed) return;
      disposed = true;
      observer.disconnect();
      controls.dispose();
      renderer.setAnimationLoop(null);
      renderer.domElement.removeEventListener('webglcontextlost', lostContext);
      disposeModel(model);
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}

function disposeModel(model) {
  const textures = new Set(), materials = new Set(), geometries = new Set();
  model.traverse((object) => {
    if (object.geometry) geometries.add(object.geometry);
    for (const material of Array.isArray(object.material) ? object.material : object.material ? [object.material] : []) {
      materials.add(material);
      for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
    }
  });
  textures.forEach((texture) => texture.dispose());
  materials.forEach((material) => material.dispose());
  geometries.forEach((geometry) => geometry.dispose());
}

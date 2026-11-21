import { useEffect, useRef, useState } from 'react';
import { Box, Eye, EyeOff, Map as MapIcon, RotateCcw, Route, Sparkles, Trees, X } from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { fetchOrchardScene } from '../../api/orchardApi';
import { HEALTH_PALETTE, HEALTH_STATUS_ORDER } from '../../constants/healthPalette';
import { useLanguage } from '../../contexts/LanguageContext';
import { useTheme } from '../../contexts/ThemeContext';
import type { OrchardSceneResponse, OrchardTree3D } from '../../types/orchard';

interface LayerVisibility {
  pointCloud: boolean;
  trees: boolean;
  rowLines: boolean;
}

const DEFAULT_CAMERA_POS = new THREE.Vector3(38, 28, 42);
const TOP_CAMERA_POS = new THREE.Vector3(0, 68, 0.01);
const DEFAULT_TARGET = new THREE.Vector3(0, 0.8, 0);

export function Orchard3DViewerCard() {
  const { t } = useLanguage();
  const { resolvedTheme } = useTheme();

  const [sceneData, setSceneData] = useState<OrchardSceneResponse | null>(null);
  const [endpoint, setEndpoint] = useState<string>('');
  const [selectedTree, setSelectedTree] = useState<OrchardTree3D | null>(null);
  const [layers, setLayers] = useState<LayerVisibility>({
    pointCloud: true,
    trees: true,
    rowLines: true,
  });

  const mountRef = useRef<HTMLDivElement | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const pointCloudGroupRef = useRef<THREE.Group | null>(null);
  const treesGroupRef = useRef<THREE.Group | null>(null);
  const rowLinesGroupRef = useRef<THREE.Group | null>(null);
  const selectionRingRef = useRef<THREE.Mesh | null>(null);
  const treeLookupRef = useRef<Map<string, OrchardTree3D>>(new Map());
  const gridHelperRef = useRef<THREE.GridHelper | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchOrchardScene(undefined, controller.signal)
      .then((res) => {
        setSceneData(res.data);
        setEndpoint(res.endpoint);
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch 3D orchard scene:', err);
        }
      });

    return () => controller.abort();
  }, []);

  // Build Three.js scene when sceneData loads
  useEffect(() => {
    const container = mountRef.current;
    if (!container || !sceneData) return;

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 480;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(46, width / height, 0.1, 400);
    camera.position.copy(DEFAULT_CAMERA_POS);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.shadowMap.enabled = false;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI / 2 - 0.04;
    controls.minDistance = 8;
    controls.maxDistance = 120;
    controls.target.copy(DEFAULT_TARGET);
    controls.update();
    controlsRef.current = controls;

    // Lighting
    const hemiLight = new THREE.HemisphereLight(0xffffff, 0x3b4a3e, 1.05);
    scene.add(hemiLight);

    const dirLight = new THREE.DirectionalLight(0xfffbeb, 1.15);
    dirLight.position.set(28, 46, 22);
    scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0x93c5fd, 0.35);
    fillLight.position.set(-30, 18, -24);
    scene.add(fillLight);

    // Subtle ground reference grid
    const grid = new THREE.GridHelper(84, 28, 0x64748b, 0x334155);
    grid.position.y = -2.25;
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.22;
    scene.add(grid);
    gridHelperRef.current = grid;

    // 1. Point Cloud Layer
    const pointCloudGroup = new THREE.Group();
    const pcGeom = new THREE.BufferGeometry();
    pcGeom.setAttribute('position', new THREE.Float32BufferAttribute(sceneData.pointCloud.positions, 3));
    pcGeom.setAttribute('color', new THREE.Float32BufferAttribute(sceneData.pointCloud.colors, 3));
    const pcMat = new THREE.PointsMaterial({
      size: 0.36,
      vertexColors: true,
      transparent: true,
      opacity: 0.82,
      sizeAttenuation: true,
    });
    const pointCloudMesh = new THREE.Points(pcGeom, pcMat);
    pointCloudGroup.add(pointCloudMesh);
    scene.add(pointCloudGroup);
    pointCloudGroupRef.current = pointCloudGroup;

    // 2. Row Lines Layer (user-drawn polylines used for tree position calculation)
    const rowLinesGroup = new THREE.Group();
    const lineMaterial = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.85,
    });

    for (const row of sceneData.rowLines) {
      const pts = row.vertices.map((v) => new THREE.Vector3(v.x, v.y + 0.12, v.z));
      const lineGeom = new THREE.BufferGeometry().setFromPoints(pts);
      const line = new THREE.Line(lineGeom, lineMaterial);
      rowLinesGroup.add(line);
    }
    scene.add(rowLinesGroup);
    rowLinesGroupRef.current = rowLinesGroup;

    // 3. Individual 3D Tree Objects Layer
    const treesGroup = new THREE.Group();
    const sharedTrunkGeom = new THREE.CylinderGeometry(0.11, 0.17, 1, 7);
    const sharedCanopyGeom = new THREE.DodecahedronGeometry(1, 1);
    const sharedTopCanopyGeom = new THREE.DodecahedronGeometry(0.72, 1);
    const trunkMaterial = new THREE.MeshStandardMaterial({
      color: 0x5c4033,
      roughness: 0.9,
      metalness: 0.05,
    });

    const canopyMaterials: Record<OrchardTree3D['healthStatus'], THREE.MeshStandardMaterial> = {
      dead: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.dead.hex3d,
        roughness: 0.85,
        metalness: 0.12,
      }),
      poor: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.poor.hex3d,
        roughness: 0.72,
        metalness: 0.06,
      }),
      moderate: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.moderate.hex3d,
        roughness: 0.72,
        metalness: 0.06,
      }),
      healthy: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.healthy.hex3d,
        roughness: 0.75,
        metalness: 0.04,
      }),
    };

    const pickableMeshes: THREE.Object3D[] = [];
    const lookup = new Map<string, OrchardTree3D>();

    for (const tree of sceneData.trees) {
      lookup.set(tree.id, tree);

      const treeNode = new THREE.Group();
      treeNode.position.set(tree.position.x, tree.position.y, tree.position.z);

      const trunkHeight = tree.heightMeters * 0.42;
      const trunk = new THREE.Mesh(sharedTrunkGeom, trunkMaterial);
      trunk.scale.set(1, trunkHeight, 1);
      trunk.position.y = trunkHeight / 2;
      trunk.userData.treeId = tree.id;
      treeNode.add(trunk);

      const canopyMat = canopyMaterials[tree.healthStatus];
      const lowerCanopy = new THREE.Mesh(sharedCanopyGeom, canopyMat);
      lowerCanopy.scale.set(
        tree.canopyRadiusMeters,
        tree.heightMeters * 0.32,
        tree.canopyRadiusMeters,
      );
      lowerCanopy.position.y = trunkHeight + tree.heightMeters * 0.2;
      lowerCanopy.userData.treeId = tree.id;
      treeNode.add(lowerCanopy);
      pickableMeshes.push(lowerCanopy);

      if (tree.healthStatus !== 'dead') {
        const upperCanopy = new THREE.Mesh(sharedTopCanopyGeom, canopyMat);
        upperCanopy.scale.set(
          tree.canopyRadiusMeters * 0.88,
          tree.heightMeters * 0.26,
          tree.canopyRadiusMeters * 0.88,
        );
        upperCanopy.position.y = trunkHeight + tree.heightMeters * 0.44;
        upperCanopy.userData.treeId = tree.id;
        treeNode.add(upperCanopy);
        pickableMeshes.push(upperCanopy);
      }

      treesGroup.add(treeNode);
    }

    treeLookupRef.current = lookup;
    scene.add(treesGroup);
    treesGroupRef.current = treesGroup;

    // Selection indicator ring on terrain under the selected tree
    const ringGeom = new THREE.RingGeometry(1.45, 1.85, 32);
    ringGeom.rotateX(-Math.PI / 2);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.95,
    });
    const selectionRing = new THREE.Mesh(ringGeom, ringMat);
    selectionRing.visible = false;
    scene.add(selectionRing);
    selectionRingRef.current = selectionRing;

    // Pointer raycasting for clicking / hovering individual 3D trees
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let pointerDownPos = { x: 0, y: 0 };

    const updatePointer = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    };

    const handlePointerDown = (event: PointerEvent) => {
      pointerDownPos = { x: event.clientX, y: event.clientY };
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (!treesGroup.visible) {
        renderer.domElement.style.cursor = 'grab';
        return;
      }
      updatePointer(event);
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(pickableMeshes, false);
      renderer.domElement.style.cursor = hits.length > 0 ? 'pointer' : 'grab';
    };

    const handlePointerUp = (event: PointerEvent) => {
      const moved = Math.hypot(event.clientX - pointerDownPos.x, event.clientY - pointerDownPos.y);
      if (moved > 5 || !treesGroup.visible) return;

      updatePointer(event);
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(pickableMeshes, false);
      if (hits.length > 0) {
        const treeId = hits[0].object.userData.treeId as string | undefined;
        if (treeId) {
          const found = treeLookupRef.current.get(treeId) ?? null;
          setSelectedTree(found);
        }
      }
    };

    renderer.domElement.addEventListener('pointerdown', handlePointerDown);
    renderer.domElement.addEventListener('pointermove', handlePointerMove);
    renderer.domElement.addEventListener('pointerup', handlePointerUp);

    // Resize observer
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.max(100, entry.contentRect.width);
        const h = Math.max(240, entry.contentRect.height);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      }
    });
    resizeObserver.observe(container);

    // Animation loop
    let animId = 0;
    const animate = () => {
      animId = window.requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(animId);
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener('pointerdown', handlePointerDown);
      renderer.domElement.removeEventListener('pointermove', handlePointerMove);
      renderer.domElement.removeEventListener('pointerup', handlePointerUp);
      controls.dispose();

      pcGeom.dispose();
      pcMat.dispose();
      lineMaterial.dispose();
      rowLinesGroup.traverse((obj) => {
        if (obj instanceof THREE.Line) obj.geometry.dispose();
      });
      sharedTrunkGeom.dispose();
      sharedCanopyGeom.dispose();
      sharedTopCanopyGeom.dispose();
      trunkMaterial.dispose();
      Object.values(canopyMaterials).forEach((m) => m.dispose());
      ringGeom.dispose();
      ringMat.dispose();

      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [sceneData]);

  // Sync theme-dependent canvas background and fog
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const bgHex = resolvedTheme === 'dark' ? 0x0b1220 : 0xf1f5f9;
    scene.background = new THREE.Color(bgHex);
    scene.fog = new THREE.Fog(bgHex, 78, 170);

    if (gridHelperRef.current) {
      (gridHelperRef.current.material as THREE.Material).opacity = resolvedTheme === 'dark' ? 0.24 : 0.35;
    }
  }, [resolvedTheme, sceneData]);

  // Sync layer visibility toggles
  useEffect(() => {
    if (pointCloudGroupRef.current) pointCloudGroupRef.current.visible = layers.pointCloud;
    if (treesGroupRef.current) treesGroupRef.current.visible = layers.trees;
    if (rowLinesGroupRef.current) rowLinesGroupRef.current.visible = layers.rowLines;
  }, [layers, sceneData]);

  // Sync selection ring around clicked tree
  useEffect(() => {
    const ring = selectionRingRef.current;
    if (!ring) return;
    if (selectedTree) {
      ring.visible = true;
      ring.position.set(selectedTree.position.x, selectedTree.position.y + 0.16, selectedTree.position.z);
    } else {
      ring.visible = false;
    }
  }, [selectedTree]);

  const setCameraPreset = (preset: 'orbit' | 'top') => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;

    if (preset === 'top') {
      camera.position.copy(TOP_CAMERA_POS);
      controls.target.set(0, 0, 0);
    } else {
      camera.position.copy(DEFAULT_CAMERA_POS);
      controls.target.copy(DEFAULT_TARGET);
    }
    controls.update();
  };

  const toggleLayer = (key: keyof LayerVisibility) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <section className="card viewer-card">
      <div className="card-header viewer-header">
        <div className="card-title-row">
          <div className="card-icon">
            <Box size={18} strokeWidth={1.9} />
          </div>
          <div>
            <h2 className="card-title">{t.orchard3d.title}</h2>
            <p className="card-subtitle">{t.orchard3d.subtitle}</p>
          </div>
        </div>

        <div className="viewer-toolbar">
          <div className="viewer-toggle-group">
            <button
              type="button"
              className={`toggle-pill${layers.pointCloud ? ' is-active' : ''}`}
              onClick={() => toggleLayer('pointCloud')}
            >
              {layers.pointCloud ? <Eye size={14} /> : <EyeOff size={14} />}
              <Sparkles size={14} />
              <span>{t.orchard3d.pointCloudLayer}</span>
            </button>

            <button
              type="button"
              className={`toggle-pill${layers.trees ? ' is-active' : ''}`}
              onClick={() => toggleLayer('trees')}
            >
              {layers.trees ? <Eye size={14} /> : <EyeOff size={14} />}
              <Trees size={14} />
              <span>{t.orchard3d.treesLayer}</span>
            </button>

            <button
              type="button"
              className={`toggle-pill${layers.rowLines ? ' is-active' : ''}`}
              onClick={() => toggleLayer('rowLines')}
            >
              {layers.rowLines ? <Eye size={14} /> : <EyeOff size={14} />}
              <Route size={14} />
              <span>{t.orchard3d.rowLinesLayer}</span>
            </button>
          </div>

          <div className="segmented-control">
            <button type="button" className="segmented-btn" onClick={() => setCameraPreset('orbit')}>
              <Box size={14} />
              <span>{t.orchard3d.viewOrbit}</span>
            </button>
            <button type="button" className="segmented-btn" onClick={() => setCameraPreset('top')}>
              <MapIcon size={14} />
              <span>{t.orchard3d.viewTop}</span>
            </button>
            <button
              type="button"
              className="segmented-btn"
              onClick={() => setCameraPreset('orbit')}
              title={t.orchard3d.resetView}
              aria-label={t.orchard3d.resetView}
            >
              <RotateCcw size={14} />
            </button>
          </div>
        </div>
      </div>

      <div className="viewer-stage">
        <div ref={mountRef} className="viewer-canvas-container" />

        {/* Top-left scene stats HUD */}
        {sceneData && (
          <div className="viewer-hud viewer-hud-top-left">
            <span className="hud-chip">
              {t.orchard3d.pointsStat}: <strong>{sceneData.pointCloud.pointCount.toLocaleString()}</strong>
            </span>
            <span className="hud-chip">
              {t.orchard3d.treesStat}: <strong>{sceneData.trees.length}</strong>
            </span>
            <span className="hud-chip">
              {t.orchard3d.rowsStat}: <strong>{sceneData.rowLines.length}</strong>
            </span>
          </div>
        )}

        {/* Top-right tree inspector card */}
        {selectedTree ? (
          <div className="tree-inspector-card">
            <div className="tree-inspector-header">
              <div>
                <div className="tree-inspector-kicker">{t.orchard3d.inspectorTitle}</div>
                <div className="tree-inspector-id">{selectedTree.id}</div>
              </div>
              <button
                type="button"
                className="icon-close-btn"
                onClick={() => setSelectedTree(null)}
                aria-label={t.orchard3d.inspectorClose}
              >
                <X size={15} />
              </button>
            </div>

            <div className="tree-inspector-grid">
              <div className="inspector-row">
                <span>{t.orchard3d.inspectorHealth}</span>
                <span className="inspector-health-pill">
                  <span
                    className="health-swatch"
                    style={{
                      backgroundColor: HEALTH_PALETTE[selectedTree.healthStatus].hex,
                      borderColor:
                        selectedTree.healthStatus === 'dead' && resolvedTheme === 'dark'
                          ? '#71717a'
                          : 'transparent',
                    }}
                  />
                  <strong>
                    {t.health.statuses[selectedTree.healthStatus]} ({selectedTree.healthScore}/100)
                  </strong>
                </span>
              </div>
              <div className="inspector-row">
                <span>{t.orchard3d.inspectorRow}</span>
                <strong>
                  {selectedTree.rowLabel} · #{selectedTree.indexInRow}
                </strong>
              </div>
              <div className="inspector-row">
                <span>{t.orchard3d.inspectorHeight}</span>
                <strong>{selectedTree.heightMeters.toFixed(2)} m</strong>
              </div>
              <div className="inspector-row">
                <span>{t.orchard3d.inspectorCanopy}</span>
                <strong>{selectedTree.canopyRadiusMeters.toFixed(2)} m</strong>
              </div>
              <div className="inspector-row">
                <span>{t.orchard3d.inspectorLocalPos}</span>
                <strong>
                  ({selectedTree.position.x}, {selectedTree.position.y}, {selectedTree.position.z})
                </strong>
              </div>
              <div className="inspector-row">
                <span>{t.orchard3d.inspectorGeo}</span>
                <strong>
                  {selectedTree.geo.lat.toFixed(5)}, {selectedTree.geo.lng.toFixed(5)}
                </strong>
              </div>
            </div>
          </div>
        ) : (
          <div className="viewer-hud viewer-hud-top-right muted-hud-hint">{t.orchard3d.selectTreePrompt}</div>
        )}

        {/* Bottom-left health color legend */}
        <div className="viewer-hud viewer-hud-bottom-left">
          {HEALTH_STATUS_ORDER.map((status) => (
            <span key={status} className="hud-legend-item">
              <span
                className="health-swatch"
                style={{
                  backgroundColor: HEALTH_PALETTE[status].hex,
                  borderColor: status === 'dead' && resolvedTheme === 'dark' ? '#71717a' : 'transparent',
                }}
              />
              {t.health.statuses[status]}
            </span>
          ))}
        </div>

        {/* Bottom-right navigation hint */}
        <div className="viewer-hud viewer-hud-bottom-right">{t.orchard3d.controlsHint}</div>
      </div>

      <div className="card-footer-meta">
        <span className="muted-caption">{sceneData?.orchardName ?? ''}</span>
        <code className="endpoint-tag">GET {endpoint} · POST /api/v1/orchard/row-lines</code>
      </div>
    </section>
  );
}

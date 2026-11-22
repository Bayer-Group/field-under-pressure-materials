import { useEffect, useRef, useState } from 'react';
import {
  Box,
  Eye,
  EyeOff,
  Loader2,
  Mountain,
  Pentagon,
  Route,
  Sparkles,
  Trees,
  X,
} from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { fetchOrchardLasBuffer, fetchOrchardScene } from '../../api/orchardApi';
import { HEALTH_PALETTE, HEALTH_STATUS_ORDER, UNRATED_HEALTH_TOKEN } from '../../constants/healthPalette';
import { useLanguage } from '../../contexts/LanguageContext';
import { useOrchard } from '../../contexts/OrchardContext';
import { useTheme } from '../../contexts/ThemeContext';
import type { GeoCoord, OrchardSceneResponse, OrchardTree3D } from '../../types/orchard';
import { geoToLasSceneXZ, wgs84ToEpsg2180 } from '../../utils/crs2180';
import { parseLasArrayBuffer, type LasColorMode, type ParsedLasCloud } from '../../utils/lasParser';
import { getZoomModifierLabel } from '../../utils/platform';

interface LayerVisibility {
  pointCloud: boolean;
  trees: boolean;
  rowLines: boolean;
  boundary: boolean;
}

/**
 * Computes scene origin & metric span in EPSG:2180 from vector geometry when no `.las` file is available.
 */
function computeGeometricBounds(sceneData: OrchardSceneResponse): {
  origin: { x: number; y: number; z: number };
  spanX: number;
  spanY: number;
} {
  const geoPoints: GeoCoord[] = [];
  if (sceneData.boundaryGeo) geoPoints.push(...sceneData.boundaryGeo);
  if (sceneData.rowsGeo) {
    for (const r of sceneData.rowsGeo) {
      geoPoints.push(r.start, r.end);
    }
  }
  for (const t of sceneData.trees) {
    geoPoints.push(t.geo);
  }

  if (geoPoints.length === 0) {
    return { origin: { x: 0, y: 0, z: 0 }, spanX: 120, spanY: 120 };
  }

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const g of geoPoints) {
    const p = wgs84ToEpsg2180(g.lat, g.lng);
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }

  return {
    origin: {
      x: (minX + maxX) / 2,
      y: (minY + maxY) / 2,
      z: 0,
    },
    spanX: Math.max(30, maxX - minX),
    spanY: Math.max(30, maxY - minY),
  };
}

export function Orchard3DViewerCard() {
  const { t, language } = useLanguage();
  const { resolvedTheme } = useTheme();
  const { selectedOrchardId } = useOrchard();

  const [sceneData, setSceneData] = useState<OrchardSceneResponse | null>(null);
  const [parsedLas, setParsedLas] = useState<ParsedLasCloud | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const [colorMode, setColorMode] = useState<LasColorMode>('rgb');
  const [verticalExaggeration, setVerticalExaggeration] = useState<number>(1.8);
  const [selectedTree, setSelectedTree] = useState<OrchardTree3D | null>(null);
  const [showZoomHint, setShowZoomHint] = useState<boolean>(false);
  const zoomHintTimerRef = useRef<number | null>(null);
  const [layers, setLayers] = useState<LayerVisibility>({
    pointCloud: true,
    trees: true,
    rowLines: true,
    boundary: true,
  });

  const mountRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const worldRootRef = useRef<THREE.Group | null>(null);
  const pointCloudGeometryRef = useRef<THREE.BufferGeometry | null>(null);
  const pointCloudGroupRef = useRef<THREE.Group | null>(null);
  const treesGroupRef = useRef<THREE.Group | null>(null);
  const rowLinesGroupRef = useRef<THREE.Group | null>(null);
  const boundaryGroupRef = useRef<THREE.Group | null>(null);
  const selectionRingRef = useRef<THREE.Mesh | null>(null);
  const treeLookupRef = useRef<Map<string, OrchardTree3D>>(new Map());
  const gridHelperRef = useRef<THREE.GridHelper | null>(null);

  // Load orchard metadata + `<orchardId>.las` binary point cloud (optional — falls back to pure geometry if absent)
  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setSelectedTree(null);

    Promise.all([
      fetchOrchardScene(selectedOrchardId, controller.signal),
      fetchOrchardLasBuffer(selectedOrchardId, controller.signal),
    ])
      .then(([sceneRes, lasRes]) => {
        setSceneData(sceneRes.data);

        if (lasRes.data) {
          try {
            const parsed = parseLasArrayBuffer(lasRes.data, { maxPoints: 180_000, filterNoise: true });
            setParsedLas(parsed);
            setColorMode(parsed.header.hasRgb ? 'rgb' : 'elevation');
          } catch (parseErr) {
            console.warn('LAS parse failed, falling back to geometric orchard render:', parseErr);
            setParsedLas(null);
          }
        } else {
          setParsedLas(null);
        }
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to load orchard 3D scene:', err);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      });

    return () => controller.abort();
  }, [selectedOrchardId]);

  // Build Three.js scene (supports both `.las` LiDAR cloud mode AND pure geometric fallback mode)
  useEffect(() => {
    const container = mountRef.current;
    if (!container || !sceneData) return;

    const width = container.clientWidth || 900;
    const height = container.clientHeight || 520;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const geoFallback = computeGeometricBounds(sceneData);
    const sceneOrigin = parsedLas ? parsedLas.origin : geoFallback.origin;
    const spanX = parsedLas ? parsedLas.header.spanMeters.x : geoFallback.spanX;
    const spanY = parsedLas ? parsedLas.header.spanMeters.y : geoFallback.spanY;
    const sampleGroundY = parsedLas ? parsedLas.sampleGroundY : () => 0;
    const activeZScale = parsedLas ? verticalExaggeration : 1;

    const maxSpan = Math.max(spanX, spanY, 40);
    const orbitPos = new THREE.Vector3(maxSpan * 0.24, maxSpan * 0.52, maxSpan * 0.68);
    const centerTarget = new THREE.Vector3(0, parsedLas ? 2.5 : 1.0, 0);

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.2, Math.max(900, maxSpan * 8));
    camera.position.copy(orbitPos);

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI / 2 - 0.03;
    controls.minDistance = 6;
    controls.maxDistance = Math.max(140, maxSpan * 1.68);
    controls.target.copy(centerTarget);
    controls.update();

    // Require Cmd/Ctrl + scroll to zoom the 3D scene; plain scroll scrolls the page naturally
    const handleWheelGuard = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) {
        event.stopImmediatePropagation();
        setShowZoomHint(true);
        if (zoomHintTimerRef.current !== null) {
          window.clearTimeout(zoomHintTimerRef.current);
        }
        zoomHintTimerRef.current = window.setTimeout(() => setShowZoomHint(false), 1400);
        return;
      }
      // Block browser page zoom when zooming the 3D scene with Cmd/Ctrl + scroll
      event.preventDefault();
    };
    renderer.domElement.addEventListener('wheel', handleWheelGuard, { capture: true, passive: false });

    // Lighting
    const hemiLight = new THREE.HemisphereLight(0xffffff, 0x3b4a3e, 1.15);
    scene.add(hemiLight);

    const dirLight = new THREE.DirectionalLight(0xfffbeb, 1.15);
    dirLight.position.set(maxSpan * 0.6, maxSpan * 0.9, maxSpan * 0.45);
    scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0x93c5fd, 0.38);
    fillLight.position.set(-maxSpan * 0.5, maxSpan * 0.35, -maxSpan * 0.45);
    scene.add(fillLight);

    // Subtle ground reference grid scaled to the orchard span
    const gridSize = Math.ceil((maxSpan * 1.25) / 20) * 20;
    const gridDivisions = Math.min(48, Math.max(16, Math.round(gridSize / 10)));
    const grid = new THREE.GridHelper(gridSize, gridDivisions, 0x64748b, 0x334155);
    grid.position.y = parsedLas ? -0.35 : -0.05;
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.2;
    scene.add(grid);
    gridHelperRef.current = grid;

    // World root group (applies vertical relief scaling when LAS is present)
    const worldRoot = new THREE.Group();
    worldRoot.scale.set(1, activeZScale, 1);
    scene.add(worldRoot);
    worldRootRef.current = worldRoot;

    // 1. Optional `.las` Point Cloud Layer
    let pcGeom: THREE.BufferGeometry | null = null;
    let pcMat: THREE.PointsMaterial | null = null;
    const pointCloudGroup = new THREE.Group();

    if (parsedLas) {
      pcGeom = new THREE.BufferGeometry();
      pcGeom.setAttribute('position', new THREE.BufferAttribute(parsedLas.positions, 3));
      const initialColors =
        colorMode === 'rgb'
          ? parsedLas.rgbColors
          : colorMode === 'classification'
            ? parsedLas.classificationColors
            : colorMode === 'intensity'
              ? parsedLas.intensityColors
              : parsedLas.elevationColors;
      pcGeom.setAttribute('color', new THREE.BufferAttribute(new Float32Array(initialColors), 3));
      pointCloudGeometryRef.current = pcGeom;

      pcMat = new THREE.PointsMaterial({
        size: Math.max(0.55, Math.min(1.4, maxSpan / 220)),
        vertexColors: true,
        transparent: false,
        sizeAttenuation: true,
      });
      const pointCloudMesh = new THREE.Points(pcGeom, pcMat);
      pointCloudGroup.add(pointCloudMesh);
    } else {
      pointCloudGeometryRef.current = null;
    }

    worldRoot.add(pointCloudGroup);
    pointCloudGroupRef.current = pointCloudGroup;

    // 2. Orchard Boundary Polygon (outline + flat geometric surface when `.las` is absent)
    const boundaryGroup = new THREE.Group();
    const boundaryMat = new THREE.LineBasicMaterial({
      color: 0x22c55e,
      transparent: true,
      opacity: 0.92,
    });
    let parcelFillGeom: THREE.ShapeGeometry | null = null;
    let parcelFillMat: THREE.MeshStandardMaterial | null = null;

    if (sceneData.boundaryGeo && sceneData.boundaryGeo.length >= 3) {
      const projectedBoundary = sceneData.boundaryGeo.map((geo) => geoToLasSceneXZ(geo, sceneOrigin));

      const boundaryPts = [...projectedBoundary, projectedBoundary[0]].map((pt) => {
        const y = sampleGroundY(pt.x, pt.z) + (parsedLas ? 0.35 : 0.08);
        return new THREE.Vector3(pt.x, y, pt.z);
      });
      const bGeom = new THREE.BufferGeometry().setFromPoints(boundaryPts);
      boundaryGroup.add(new THREE.Line(bGeom, boundaryMat));

      // In geometric-only mode (no `.las`), render a crisp filled orchard ground plane
      if (!parsedLas) {
        const shape = new THREE.Shape();
        projectedBoundary.forEach((pt, idx) => {
          // Shape lies in XY, rotated -90deg around X -> (x, -z) maps to (x, 0, z)
          if (idx === 0) shape.moveTo(pt.x, -pt.z);
          else shape.lineTo(pt.x, -pt.z);
        });
        shape.closePath();

        parcelFillGeom = new THREE.ShapeGeometry(shape);
        parcelFillGeom.rotateX(-Math.PI / 2);
        parcelFillMat = new THREE.MeshStandardMaterial({
          color: 0x16a34a,
          roughness: 0.92,
          metalness: 0.02,
          transparent: true,
          opacity: 0.16,
          side: THREE.DoubleSide,
        });
        const parcelMesh = new THREE.Mesh(parcelFillGeom, parcelFillMat);
        parcelMesh.position.y = 0.01;
        boundaryGroup.add(parcelMesh);
      }
    }
    worldRoot.add(boundaryGroup);
    boundaryGroupRef.current = boundaryGroup;

    // 3. Row Lines Layer (projected from WGS 84 -> EPSG:2180 -> terrain/flat ground)
    const rowLinesGroup = new THREE.Group();
    const lineMaterial = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.95,
    });
    if (sceneData.rowsGeo && sceneData.rowsGeo.length > 0) {
      for (const row of sceneData.rowsGeo) {
        const startXZ = geoToLasSceneXZ(row.start, sceneOrigin);
        const endXZ = geoToLasSceneXZ(row.end, sceneOrigin);
        const pts: THREE.Vector3[] = [];
        const steps = parsedLas ? 12 : 2;
        for (let s = 0; s <= steps; s += 1) {
          const tStep = s / steps;
          const px = startXZ.x + (endXZ.x - startXZ.x) * tStep;
          const pz = startXZ.z + (endXZ.z - startXZ.z) * tStep;
          const py = sampleGroundY(px, pz) + (parsedLas ? 0.25 : 0.12);
          pts.push(new THREE.Vector3(px, py, pz));
        }
        const lineGeom = new THREE.BufferGeometry().setFromPoints(pts);
        rowLinesGroup.add(new THREE.Line(lineGeom, lineMaterial));
      }
    }
    worldRoot.add(rowLinesGroup);
    rowLinesGroupRef.current = rowLinesGroup;

    // 4. Individual 3D Tree Objects Layer
    const treesGroup = new THREE.Group();
    const sharedTrunkGeom = new THREE.CylinderGeometry(0.14, 0.22, 1, 7);
    const sharedCanopyGeom = new THREE.DodecahedronGeometry(1, 1);
    const sharedTopCanopyGeom = new THREE.DodecahedronGeometry(0.72, 1);
    const trunkMaterial = new THREE.MeshStandardMaterial({
      color: 0x5c4033,
      roughness: 0.9,
      metalness: 0.05,
    });

    const canopyMaterials: Record<'dead' | 'poor' | 'moderate' | 'healthy' | 'unrated', THREE.MeshStandardMaterial> = {
      dead: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.dead.hex3d,
        roughness: 0.85,
        metalness: 0.12,
      }),
      poor: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.poor.hex3d,
        roughness: 0.7,
        metalness: 0.06,
      }),
      moderate: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.moderate.hex3d,
        roughness: 0.7,
        metalness: 0.06,
      }),
      healthy: new THREE.MeshStandardMaterial({
        color: HEALTH_PALETTE.healthy.hex3d,
        roughness: 0.72,
        metalness: 0.04,
      }),
      unrated: new THREE.MeshStandardMaterial({
        color: UNRATED_HEALTH_TOKEN.hex3d,
        roughness: 0.76,
        metalness: 0.05,
      }),
    };

    const pickableMeshes: THREE.Object3D[] = [];
    const lookup = new Map<string, OrchardTree3D>();

    for (const tree of sceneData.trees) {
      const xz = geoToLasSceneXZ(tree.geo, sceneOrigin);
      const groundY = sampleGroundY(xz.x, xz.z);
      const alignedTree: OrchardTree3D = {
        ...tree,
        position: {
          x: Number(xz.x.toFixed(2)),
          y: Number(groundY.toFixed(2)),
          z: Number(xz.z.toFixed(2)),
        },
      };
      lookup.set(alignedTree.id, alignedTree);

      const treeNode = new THREE.Group();
      treeNode.position.set(xz.x, groundY, xz.z);

      const trunkHeight = tree.heightMeters * 0.44;
      const trunk = new THREE.Mesh(sharedTrunkGeom, trunkMaterial);
      trunk.scale.set(1, trunkHeight, 1);
      trunk.position.y = trunkHeight / 2;
      trunk.userData.treeId = alignedTree.id;
      treeNode.add(trunk);

      const canopyMat = canopyMaterials[tree.healthStatus ?? 'unrated'];
      const lowerCanopy = new THREE.Mesh(sharedCanopyGeom, canopyMat);
      lowerCanopy.scale.set(
        tree.canopyRadiusMeters,
        tree.heightMeters * 0.34,
        tree.canopyRadiusMeters,
      );
      lowerCanopy.position.y = trunkHeight + tree.heightMeters * 0.22;
      lowerCanopy.userData.treeId = alignedTree.id;
      treeNode.add(lowerCanopy);
      pickableMeshes.push(lowerCanopy);

      if (tree.healthStatus !== 'dead') {
        const upperCanopy = new THREE.Mesh(sharedTopCanopyGeom, canopyMat);
        upperCanopy.scale.set(
          tree.canopyRadiusMeters * 0.86,
          tree.heightMeters * 0.26,
          tree.canopyRadiusMeters * 0.86,
        );
        upperCanopy.position.y = trunkHeight + tree.heightMeters * 0.46;
        upperCanopy.userData.treeId = alignedTree.id;
        treeNode.add(upperCanopy);
        pickableMeshes.push(upperCanopy);
      }

      treesGroup.add(treeNode);
    }

    treeLookupRef.current = lookup;
    worldRoot.add(treesGroup);
    treesGroupRef.current = treesGroup;

    // Selection indicator ring under the selected tree
    const ringGeom = new THREE.RingGeometry(1.5, 2.0, 32);
    ringGeom.rotateX(-Math.PI / 2);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.95,
    });
    const selectionRing = new THREE.Mesh(ringGeom, ringMat);
    selectionRing.visible = false;
    worldRoot.add(selectionRing);
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

    let animId = 0;
    const animate = () => {
      animId = window.requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(animId);
      if (zoomHintTimerRef.current !== null) {
        window.clearTimeout(zoomHintTimerRef.current);
      }
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener('wheel', handleWheelGuard, { capture: true });
      renderer.domElement.removeEventListener('pointerdown', handlePointerDown);
      renderer.domElement.removeEventListener('pointermove', handlePointerMove);
      renderer.domElement.removeEventListener('pointerup', handlePointerUp);
      controls.dispose();

      pcGeom?.dispose();
      pcMat?.dispose();
      parcelFillGeom?.dispose();
      parcelFillMat?.dispose();
      boundaryMat.dispose();
      boundaryGroup.traverse((obj) => {
        if (obj instanceof THREE.Line) obj.geometry.dispose();
      });
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
  }, [parsedLas, sceneData]);

  // Sync theme-dependent canvas background and subtle distance-scaled horizon fog
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const bgHex = resolvedTheme === 'dark' ? 0x0b1220 : 0xeef2f6;
    scene.background = new THREE.Color(bgHex);

    const geoFallback = sceneData ? computeGeometricBounds(sceneData) : { spanX: 120, spanY: 120 };
    const spanX = parsedLas ? parsedLas.header.spanMeters.x : geoFallback.spanX;
    const spanY = parsedLas ? parsedLas.header.spanMeters.y : geoFallback.spanY;
    const maxSpan = Math.max(spanX, spanY, 40);
    scene.fog = new THREE.Fog(bgHex, Math.max(700, maxSpan * 4.5), Math.max(2200, maxSpan * 11));

    if (gridHelperRef.current) {
      (gridHelperRef.current.material as THREE.Material).opacity = resolvedTheme === 'dark' ? 0.2 : 0.32;
    }
  }, [resolvedTheme, parsedLas, sceneData]);

  // Sync point cloud color mode (RGB / Elevation / Classification) without rebuilding scene
  useEffect(() => {
    const geom = pointCloudGeometryRef.current;
    if (!geom || !parsedLas) return;
    const nextArr =
      colorMode === 'rgb'
        ? parsedLas.rgbColors
        : colorMode === 'classification'
          ? parsedLas.classificationColors
          : colorMode === 'intensity'
            ? parsedLas.intensityColors
            : parsedLas.elevationColors;
    const attr = geom.getAttribute('color') as THREE.BufferAttribute | undefined;
    if (attr && attr.array.length === nextArr.length) {
      (attr.array as Float32Array).set(nextArr);
      attr.needsUpdate = true;
    }
  }, [colorMode, parsedLas]);

  // Sync vertical relief scale (Z x1 / x1.8 / x2.8) when LAS is active
  useEffect(() => {
    if (worldRootRef.current) {
      worldRootRef.current.scale.set(1, parsedLas ? verticalExaggeration : 1, 1);
    }
  }, [verticalExaggeration, parsedLas]);

  // Sync layer visibility toggles
  useEffect(() => {
    if (pointCloudGroupRef.current) pointCloudGroupRef.current.visible = layers.pointCloud;
    if (treesGroupRef.current) treesGroupRef.current.visible = layers.trees;
    if (rowLinesGroupRef.current) rowLinesGroupRef.current.visible = layers.rowLines;
    if (boundaryGroupRef.current) boundaryGroupRef.current.visible = layers.boundary;
  }, [layers, parsedLas, sceneData]);

  // Sync selection ring around clicked tree
  useEffect(() => {
    const ring = selectionRingRef.current;
    if (!ring) return;
    if (selectedTree) {
      ring.visible = true;
      ring.position.set(selectedTree.position.x, selectedTree.position.y + 0.22, selectedTree.position.z);
    } else {
      ring.visible = false;
    }
  }, [selectedTree]);

  const toggleLayer = (key: keyof LayerVisibility) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const colorModes: Array<{ id: LasColorMode; label: string }> = [
    { id: 'rgb', label: t.orchard3d.colorRgb },
    { id: 'elevation', label: t.orchard3d.colorElevation },
    { id: 'classification', label: t.orchard3d.colorClass },
    { id: 'intensity', label: t.orchard3d.colorIntensity },
  ];

  const zoomMod = getZoomModifierLabel();

  return (
    <section className="card viewer-card">
      <div className="card-header viewer-header">
        <div className="card-title-row">
          <div className="card-icon">
            <Box size={18} strokeWidth={1.9} />
          </div>
          <h2 className="card-title">
            {t.orchard3d.title}
            {sceneData?.orchardName ? ` — ${sceneData.orchardName}` : ''}
          </h2>
        </div>

        <div className="viewer-toolbar">
          {/* Layer toggles */}
          <div className="viewer-toggle-group">
            {parsedLas && (
              <button
                type="button"
                className={`toggle-pill${layers.pointCloud ? ' is-active' : ''}`}
                onClick={() => toggleLayer('pointCloud')}
              >
                {layers.pointCloud ? <Eye size={14} /> : <EyeOff size={14} />}
                <Sparkles size={14} />
                <span>{t.orchard3d.pointCloudLayer}</span>
              </button>
            )}

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

            <button
              type="button"
              className={`toggle-pill${layers.boundary ? ' is-active' : ''}`}
              onClick={() => toggleLayer('boundary')}
            >
              {layers.boundary ? <Eye size={14} /> : <EyeOff size={14} />}
              <Pentagon size={14} />
              <span>{t.orchard3d.boundaryLayer}</span>
            </button>
          </div>

          {/* LAS Color Mode & Relief Boost (only shown when `<_id>.las` is loaded) */}
          {parsedLas && (
            <>
              <div className="segmented-control" role="group" aria-label={t.orchard3d.colorModeLabel}>
                {colorModes.map((mode) => (
                  <button
                    key={mode.id}
                    type="button"
                    className={`segmented-btn${colorMode === mode.id ? ' is-active' : ''}`}
                    onClick={() => setColorMode(mode.id)}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>

              <button
                type="button"
                className={`toggle-pill${verticalExaggeration > 1 ? ' is-active' : ''}`}
                onClick={() => setVerticalExaggeration((z) => (z === 1 ? 1.8 : z === 1.8 ? 2.8 : 1))}
                title={t.orchard3d.reliefTooltip}
              >
                <Mountain size={14} />
                <span>Z ×{verticalExaggeration}</span>
              </button>
            </>
          )}
        </div>
      </div>

      <div className="viewer-stage">
        <div ref={mountRef} className="viewer-canvas-container" />

        {showZoomHint && (
          <div className="map-zoom-hint-toast" role="status">
            {t.orchard3d.zoomModifierHint.replace('{mod}', zoomMod)}
          </div>
        )}

        {isLoading && (
          <div className="viewer-loading-overlay">
            <Loader2 size={22} className="spin-icon" />
            <span>{t.orchard3d.loadingLas}</span>
          </div>
        )}

        {/* Top-left scene stats HUD */}
        {sceneData && (
          <div className="viewer-hud viewer-hud-top-left">
            {parsedLas ? (
              <span className="hud-chip">
                {parsedLas.header.spanMeters.x.toFixed(0)} × {parsedLas.header.spanMeters.y.toFixed(0)} m
              </span>
            ) : (
              <span className="hud-chip">{t.orchard3d.geometricFallbackLabel}</span>
            )}
            <span className="hud-chip">
              {t.orchard3d.treesStat}: <strong>{sceneData.trees.length}</strong>
            </span>
          </div>
        )}

        {/* Top-right tree inspector card */}
        {selectedTree ? (
          <div className="tree-inspector-card">
            <div className="tree-inspector-header">
              <div>
                <div className="tree-inspector-kicker">{t.orchard3d.inspectorTitle}</div>
                <div className="tree-inspector-id">
                  {t.orchard3d.inspectorRow}: {selectedTree.rowLabel} · #{selectedTree.indexInRow}
                </div>
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
                      backgroundColor: selectedTree.healthStatus
                        ? HEALTH_PALETTE[selectedTree.healthStatus].hex
                        : UNRATED_HEALTH_TOKEN.hex,
                      borderColor:
                        selectedTree.healthStatus === 'dead' && resolvedTheme === 'dark'
                          ? '#71717a'
                          : 'transparent',
                    }}
                  />
                  <strong>
                    {selectedTree.healthStatus && selectedTree.healthScore !== null
                      ? `${t.health.statuses[selectedTree.healthStatus]} (${selectedTree.healthScore}/100)`
                      : t.health.statuses.unrated}
                    {selectedTree.healthSource === 'estimate' && (
                      <small> · {language === 'pl' ? 'Szacunek ML' : 'ML estimate'} · {selectedTree.healthCoverage}%</small>
                    )}
                  </strong>
                </span>
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
                  {selectedTree.geo.lat.toFixed(6)}, {selectedTree.geo.lng.toFixed(6)}
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
        <div className="viewer-hud viewer-hud-bottom-right">
          {t.orchard3d.controlsHint.replace('{mod}', zoomMod)}
        </div>
      </div>
    </section>
  );
}

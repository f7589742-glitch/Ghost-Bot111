"use client";

import React, { useEffect, useRef } from "react";
import * as THREE from "three";

export default function TacticalCanvas3D() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // 1. Scene & Camera Setup
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      48,
      container.clientWidth / container.clientHeight,
      0.1,
      100
    );
    camera.position.set(0, 4, 14);

    // 2. WebGL Renderer with High Performance
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    container.appendChild(renderer.domElement);

    // 3. Dynamic Tactical Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const pointGreen = new THREE.PointLight(0x10b981, 2.5, 30);
    pointGreen.position.set(0, 10, 5);
    scene.add(pointGreen);

    const pointGold = new THREE.PointLight(0xf59e0b, 2.0, 25);
    pointGold.position.set(10, -5, 2);
    scene.add(pointGold);

    const pointCyan = new THREE.PointLight(0x06b6d4, 1.8, 25);
    pointCyan.position.set(-10, 5, -2);
    scene.add(pointCyan);

    // 4. Rotating Wireframe Hologram Terrain
    const terrainGeo = new THREE.PlaneGeometry(38, 38, 28, 28);
    const pos = terrainGeo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      const z = Math.sin(x * 0.3) * Math.cos(y * 0.3) * 1.2 + Math.sin((x + y) * 0.2) * 0.8;
      pos.setZ(i, z);
    }
    terrainGeo.computeVertexNormals();

    const terrainMat = new THREE.MeshBasicMaterial({
      color: 0x0ea5e9,
      wireframe: true,
      transparent: true,
      opacity: 0.14,
    });

    const terrainMesh = new THREE.Mesh(terrainGeo, terrainMat);
    const gridHelper = new THREE.GridHelper(42, 28, 0x10b981, 0x1e293b);
    gridHelper.position.set(0, 0, -0.1);

    const terrainGroup = new THREE.Group();
    terrainGroup.rotation.set(-Math.PI / 2.3, 0, 0);
    terrainGroup.position.set(0, -3.8, -2);
    terrainGroup.add(terrainMesh);
    terrainGroup.add(gridHelper);
    scene.add(terrainGroup);

    // 5. Floating Cyber Embers & Data Particles
    const emberCount = 160;
    const emberPositions = new Float32Array(emberCount * 3);
    const emberColors = new Float32Array(emberCount * 3);

    const colorGold = new THREE.Color("#f59e0b");
    const colorEmerald = new THREE.Color("#10b981");
    const colorCyan = new THREE.Color("#06b6d4");

    for (let i = 0; i < emberCount; i++) {
      emberPositions[i * 3] = (Math.random() - 0.5) * 32;
      emberPositions[i * 3 + 1] = Math.random() * 16 - 4;
      emberPositions[i * 3 + 2] = (Math.random() - 0.5) * 24;

      const pick = Math.random();
      const c = pick > 0.6 ? colorGold : pick > 0.3 ? colorEmerald : colorCyan;
      emberColors[i * 3] = c.r;
      emberColors[i * 3 + 1] = c.g;
      emberColors[i * 3 + 2] = c.b;
    }

    const emberGeo = new THREE.BufferGeometry();
    emberGeo.setAttribute("position", new THREE.BufferAttribute(emberPositions, 3));
    emberGeo.setAttribute("color", new THREE.BufferAttribute(emberColors, 3));

    const emberMat = new THREE.PointsMaterial({
      size: 0.16,
      vertexColors: true,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const embers = new THREE.Points(emberGeo, emberMat);
    scene.add(embers);

    // 6. Mouse Parallax Tracking
    let mouseX = 0;
    let mouseY = 0;
    const targetCameraPos = new THREE.Vector3(0, 4, 14);

    const handleMouseMove = (e: MouseEvent) => {
      const x = (e.clientX / window.innerWidth) * 2 - 1;
      const y = -(e.clientY / window.innerHeight) * 2 + 1;
      mouseX = x;
      mouseY = y;
    };
    window.addEventListener("mousemove", handleMouseMove);

    // 7. Render Loop (Strict 60 FPS budget)
    let animationId: number;
    const clock = new THREE.Clock();

    const animate = () => {
      animationId = requestAnimationFrame(animate);
      const elapsed = clock.getElapsedTime();

      // Slow terrain rotation
      terrainGroup.rotation.z = elapsed * 0.025;

      // Drift particles upward
      const pAttr = emberGeo.attributes.position;
      for (let i = 0; i < emberCount; i++) {
        let y = pAttr.getY(i) + 0.015;
        if (y > 12) y = -4;
        pAttr.setY(i, y);

        const x = pAttr.getX(i) + Math.sin(elapsed + i) * 0.003;
        pAttr.setX(i, x);
      }
      pAttr.needsUpdate = true;

      // Damped camera movement
      targetCameraPos.set(mouseX * 2.5, mouseY * 1.5 + 4, 14);
      camera.position.lerp(targetCameraPos, 0.035);
      camera.lookAt(0, 0, 0);

      renderer.render(scene, camera);
    };
    animate();

    // 8. Resize Handler
    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", handleResize);

    // Cleanup
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("resize", handleResize);
      cancelAnimationFrame(animationId);
      renderer.dispose();
      terrainGeo.dispose();
      terrainMat.dispose();
      emberGeo.dispose();
      emberMat.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
      <div ref={containerRef} className="w-full h-full" />
      {/* Holographic Vignette & Radial Gradients */}
      <div className="absolute inset-0 bg-gradient-to-b from-[#06080d]/40 via-transparent to-[#06080d]/90 pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-transparent via-[#06080d]/30 to-[#06080d]/95 pointer-events-none" />
    </div>
  );
}
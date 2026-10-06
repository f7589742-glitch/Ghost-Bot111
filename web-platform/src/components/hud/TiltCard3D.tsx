"use client";

import React, { useRef } from "react";
import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";

interface TiltCard3DProps {
  children: React.ReactNode;
  className?: string;
  glowColor?: "emerald" | "gold" | "cyan" | "rose" | "default";
  cornerBrackets?: boolean;
  onClick?: () => void;
}

export default function TiltCard3D({
  children,
  className = "",
  glowColor = "default",
  cornerBrackets = true,
  onClick,
}: TiltCard3DProps) {
  const cardRef = useRef<HTMLDivElement>(null);

  const x = useMotionValue(0);
  const y = useMotionValue(0);

  // Smooth spring physics for silky 60 FPS tilt
  const mouseXSpring = useSpring(x, { stiffness: 260, damping: 24 });
  const mouseYSpring = useSpring(y, { stiffness: 260, damping: 24 });

  const rotateX = useTransform(mouseYSpring, [-0.5, 0.5], ["9deg", "-9deg"]);
  const rotateY = useTransform(mouseXSpring, [-0.5, 0.5], ["-9deg", "9deg"]);

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const xPct = mouseX / width - 0.5;
    const yPct = mouseY / height - 0.5;
    x.set(xPct);
    y.set(yPct);
  }

  function handleMouseLeave() {
    x.set(0);
    y.set(0);
  }

  const glowStyles = {
    default: "border-[#1f293d] hover:border-emerald-500/40 hover:shadow-[0_0_25px_rgba(16,185,129,0.12)]",
    emerald: "border-emerald-500/30 hover:border-emerald-400/60 shadow-[0_0_20px_rgba(16,185,129,0.1)] hover:shadow-[0_0_35px_rgba(16,185,129,0.22)]",
    gold: "border-amber-500/30 hover:border-amber-400/60 shadow-[0_0_20px_rgba(245,158,11,0.1)] hover:shadow-[0_0_35px_rgba(245,158,11,0.22)]",
    cyan: "border-cyan-500/30 hover:border-cyan-400/60 shadow-[0_0_20px_rgba(6,182,212,0.1)] hover:shadow-[0_0_35px_rgba(6,182,212,0.22)]",
    rose: "border-rose-500/30 hover:border-rose-400/60 shadow-[0_0_20px_rgba(244,63,94,0.1)] hover:shadow-[0_0_35px_rgba(244,63,94,0.22)]",
  }[glowColor];

  return (
    <motion.div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      onClick={onClick}
      style={{
        rotateX,
        rotateY,
        transformStyle: "preserve-3d",
      }}
      className={`relative rounded-xl bg-[#0a0e17]/80 backdrop-blur-xl border transition-colors duration-200 ${glowStyles} ${cornerBrackets ? "hud-corner-bracket" : ""} ${className}`}
    >
      <div style={{ transform: "translateZ(20px)" }} className="relative z-10 w-full h-full">
        {children}
      </div>
    </motion.div>
  );
}
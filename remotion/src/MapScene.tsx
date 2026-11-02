import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {geoBounds, geoCentroid, geoInterpolate, geoNaturalEarth1, geoOrthographic, geoPath} from 'd3-geo';
import {feature} from 'topojson-client';
import world from 'world-atlas/countries-50m.json';

/* Animated map scenes for Nation Inc. (free, generated from Natural Earth data — no stock footage needed).
   kind = 'zoom'   : globe spins and zooms into the country
          'pin'    : country close-up with a pulsing pin on the capital ("HQ")
          'routes' : flat world map, trade lines fly from the country to its biggest customers
          'rivals' : flat world map, the country vs its competitors highlighted                     */

export type MapGraphic = {
  type: 'map'; s: number; e: number; kind: 'zoom' | 'pin' | 'routes' | 'rivals';
  focus: string; label: string; title?: string;
  pin?: {lon: number; lat: number; label: string} | null;
  targets?: {id: string; label: string}[];
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const FEATURES: any[] = (feature(world as any, (world as any).objects.countries) as any).features;
const GOLD = '#D4AF37';
const W = 1920;
const H = 1080;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const byId = (id: string): any => FEATURES.find((f) => String(f.id) === String(id));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function zoomScale(f: any): number {
  const [[x0, y0], [x1, y1]] = geoBounds(f);
  let dlon = x1 - x0;
  if (dlon < 0) dlon += 360;
  const lat = (y0 + y1) / 2;
  const span = Math.max(dlon * Math.cos((lat * Math.PI) / 180), y1 - y0, 0.5);
  return Math.max(460, Math.min(9000, 520 / ((span * Math.PI) / 180)));
}

const Label: React.FC<{text: string; sub?: string; op: number}> = ({text, sub, op}) => (
  <div style={{position: 'absolute', left: 0, right: 0, bottom: 150, textAlign: 'center', opacity: op}}>
    {sub ? <div style={{fontFamily: 'Poppins', fontWeight: 800, fontSize: 30, letterSpacing: 10, color: GOLD}}>{sub}</div> : null}
    <div style={{fontFamily: 'Anton', fontSize: 120, color: 'white', textTransform: 'uppercase', lineHeight: 1.05,
                 textShadow: '0 10px 40px rgba(0,0,0,0.8)'}}>{text}</div>
  </div>
);

export const MapScene: React.FC<{g: MapGraphic; frames: number}> = ({g, frames}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const focus = byId(g.focus);
  const fadeIn = interpolate(f, [0, 10], [0, 1], clamp);
  const fadeOut = interpolate(f, [frames - 10, frames], [1, 0], clamp);
  if (!focus) return null;
  const [clon, clat] = geoCentroid(focus);
  const flat = g.kind === 'routes' || g.kind === 'rivals';

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let projection: any;
  if (flat) {
    projection = geoNaturalEarth1().rotate([-clon, 0]).fitExtent([[60, 120], [W - 60, H - 60]], {type: 'Sphere'});
  } else {
    const target = zoomScale(focus);
    const p = g.kind === 'zoom'
      ? interpolate(f, [8, Math.min(frames - 25, Math.round(3.2 * fps))], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)})
      : 1;
    const startRot = [-(clon - 70), -(clat * 0.3)];
    const rot = [startRot[0] + (-clon - startRot[0]) * p, startRot[1] + (-clat - startRot[1]) * p];
    const scale = Math.exp(Math.log(430) + (Math.log(target) - Math.log(430)) * p);
    projection = geoOrthographic().rotate([rot[0], rot[1], 0]).scale(scale).translate([W / 2, H / 2 - 30]).clipAngle(90);
  }
  const path = geoPath(projection);
  const targets = (g.targets || []).map((t) => ({...t, f: byId(t.id)})).filter((t) => t.f);
  const tIds = new Set(targets.map((t) => String(t.id)));
  const glow = 0.55 + 0.45 * Math.sin((f / fps) * Math.PI * 1.6);

  // trade routes
  const routeProg = interpolate(f, [12, Math.min(frames - 20, 70)], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const routes = g.kind === 'routes' ? targets.map((t, i) => {
    const a: [number, number] = [clon, clat];
    const b = geoCentroid(t.f) as [number, number];
    const interp = geoInterpolate(a, b);
    const local = Math.max(0, Math.min(1, routeProg * 1.4 - i * 0.12));
    const pts: [number, number][] = [];
    for (let k = 0; k <= 40; k++) pts.push(interp((k / 40) * local));
    return {d: path({type: 'LineString', coordinates: pts}) || '', end: projection(interp(local)), local, label: t.label, b: projection(b)};
  }) : [];

  const sphere = path({type: 'Sphere'}) || '';
  const pinXY = g.pin ? projection([g.pin.lon, g.pin.lat]) : null;
  const pinPop = spring({frame: f - 14, fps, config: {damping: 10, stiffness: 160}, durationInFrames: 16});
  const labelOp = g.kind === 'zoom' ? interpolate(f, [Math.round(2.4 * fps), Math.round(3.0 * fps)], [0, 1], clamp) : interpolate(f, [8, 18], [0, 1], clamp);

  return (
    <AbsoluteFill style={{opacity: Math.min(fadeIn, fadeOut), background: 'radial-gradient(circle at 50% 45%, #10203a 0%, #070b13 70%)'}}>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
        <defs>
          <filter id="glow"><feGaussianBlur stdDeviation="6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {!flat ? <path d={sphere} fill="#0c1a30" stroke="rgba(212,175,55,0.25)" strokeWidth={2} /> : <path d={sphere} fill="#0a1526" />}
        {FEATURES.map((c, i) => {
          const isF = String(c.id) === String(g.focus);
          const isT = tIds.has(String(c.id));
          if (isF) return null;
          return <path key={i} d={path(c) || ''} fill={isT ? (g.kind === 'rivals' ? '#c9c9c9' : '#8a7a3e') : '#273041'}
                       stroke="#0b0f17" strokeWidth={0.6} />;
        })}
        <path d={path(focus) || ''} fill={GOLD} stroke="#fff4c4" strokeWidth={1.5} filter="url(#glow)" opacity={0.85 + 0.15 * glow} />
        {routes.map((r, i) => (
          <g key={`r${i}`}>
            <path d={r.d} fill="none" stroke={GOLD} strokeWidth={4} strokeDasharray="14 10" opacity={0.95} />
            {r.end && r.local > 0.02 ? <circle cx={r.end[0]} cy={r.end[1]} r={9} fill="white" /> : null}
          </g>
        ))}
        {pinXY && g.kind === 'pin' ? (
          <g transform={`translate(${pinXY[0]},${pinXY[1]})`}>
            <circle r={18 + 30 * ((f % 30) / 30)} fill="none" stroke={GOLD} strokeWidth={3} opacity={1 - (f % 30) / 30} />
            <g transform={`scale(${pinPop})`}>
              <path d="M0,0 C-22,-30 -22,-58 0,-62 C22,-58 22,-30 0,0 Z" transform="translate(0,-4)" fill={GOLD} stroke="white" strokeWidth={3} />
              <circle cy={-46} r={8} fill="#0a0a0a" />
            </g>
          </g>
        ) : null}
      </svg>
      {routes.map((r, i) => r.b && r.local > 0.95 ? (
        <div key={`l${i}`} style={{position: 'absolute', left: r.b[0] + 14, top: r.b[1] - 22, fontFamily: 'Poppins', fontWeight: 800,
                                    fontSize: 26, color: 'white', textShadow: '0 2px 8px #000', textTransform: 'uppercase'}}>{r.label}</div>
      ) : null)}
      {g.kind === 'rivals' ? targets.map((t, i) => {
        const xy = projection(geoCentroid(t.f));
        const op = interpolate(f, [14 + i * 6, 24 + i * 6], [0, 1], clamp);
        return xy ? (
          <div key={`v${i}`} style={{position: 'absolute', left: xy[0] - 140, width: 280, top: xy[1] - 20 + (i % 2 ? 34 : -34) * (targets.length > 2 ? 1 : 0), textAlign: 'center', opacity: op,
                                     fontFamily: 'Poppins', fontWeight: 800, fontSize: 26, color: '#0a0a0a'}}>
            <span style={{background: 'white', padding: '4px 12px', borderRadius: 6}}>{t.label}</span>
          </div>
        ) : null;
      }) : null}
      {pinXY && g.kind === 'pin' && g.pin ? (
        <div style={{position: 'absolute', left: pinXY[0] + 40, top: pinXY[1] - 110, opacity: pinPop,
                     fontFamily: 'Poppins', fontWeight: 800, fontSize: 34, color: '#0a0a0a'}}>
          <span style={{background: GOLD, padding: '8px 18px', borderRadius: 8}}>{g.pin.label}</span>
        </div>
      ) : null}
      {g.title ? (
        <div style={{position: 'absolute', top: 60, left: 0, right: 0, textAlign: 'center', fontFamily: 'Poppins', fontWeight: 800,
                     fontSize: 40, letterSpacing: 6, color: GOLD, textTransform: 'uppercase', opacity: labelOp}}>{g.title}</div>
      ) : null}
      {g.kind === 'zoom' ? <Label text={g.label} sub="COMPANY PROFILE" op={labelOp} /> : null}
    </AbsoluteFill>
  );
};

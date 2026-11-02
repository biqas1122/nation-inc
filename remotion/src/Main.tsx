import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {loadFont} from '@remotion/fonts';
import {MapScene} from './MapScene';
import type {Appearance, CaptionPage, Chapter, CharacterProps, CompanyCard, Graphic, Headline, Shot, VideoProps} from './types';

export const GOLD = '#D4AF37';
export const HEAD = 'Anton';
export const BODY = 'Poppins';
export const OVERLAP = 8;
// thick black outline that stays outside the letters (no overlap with neighbouring words)
export const OUTLINE = [
  ...Array.from({length: 16}, (_, i) => {
    const a = (i / 16) * Math.PI * 2;
    return `${(Math.cos(a) * 5).toFixed(1)}px ${(Math.sin(a) * 5).toFixed(1)}px 0 #000`;
  }),
  '0 8px 20px rgba(0,0,0,0.65)',
].join(', '); // frames of crossfade / whip between shots

loadFont({family: HEAD, url: staticFile('fonts/Anton-Regular.ttf')});
loadFont({family: BODY, url: staticFile('fonts/Poppins-Bold.ttf'), weight: '700'});
loadFont({family: BODY, url: staticFile('fonts/Poppins-ExtraBold.ttf'), weight: '800'});

export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/* ------------------------------------------------------------------ shots */

export const ShotView: React.FC<{shot: Shot; frames: number; first: boolean}> = ({shot, frames, first}) => {
  const f = useCurrentFrame();
  const p = f / Math.max(1, frames);
  let scale = 1.08;
  let x = 0;
  if (shot.motion === 'in') scale = interpolate(p, [0, 1], [1.04, 1.16]);
  if (shot.motion === 'out') scale = interpolate(p, [0, 1], [1.16, 1.04]);
  if (shot.motion === 'left') x = interpolate(p, [0, 1], [3, -3]);
  if (shot.motion === 'right') x = interpolate(p, [0, 1], [-3, 3]);

  let opacity = 1;
  let tx = 0;
  let blur = 0;
  if (!first && shot.transition === 'fade') opacity = interpolate(f, [0, OVERLAP], [0, 1], clamp);
  if (!first && shot.transition === 'whip') {
    tx = interpolate(f, [0, OVERLAP], [100, 0], {...clamp, easing: Easing.out(Easing.cubic)});
    blur = interpolate(f, [0, OVERLAP], [24, 0], clamp);
  }

  const media =
    shot.type === 'video' ? (
      <OffthreadVideo
        src={staticFile(shot.src)}
        muted
        trimBefore={Math.round((shot.trim || 0) * 30)}
        playbackRate={shot.rate || 1}
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />
    ) : (
      <Img src={staticFile(shot.src)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
    );

  return (
    <AbsoluteFill style={{opacity, transform: `translateX(${tx}%)`, filter: blur ? `blur(${blur}px)` : undefined}}>
      <AbsoluteFill style={{transform: `scale(${scale}) translateX(${x}%)`, filter: 'contrast(1.06) saturate(1.08)'}}>
        {media}
      </AbsoluteFill>
      {shot.credit ? (
        <div style={{position: 'absolute', left: 40, bottom: 22, fontFamily: BODY, fontSize: 18, color: 'rgba(255,255,255,0.7)'}}>
          {shot.credit}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const Flash: React.FC = () => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{background: 'white', opacity: interpolate(f, [0, 2, 7], [0, 0.85, 0], clamp)}} />;
};

/* --------------------------------------------------------------- captions */

const Captions: React.FC<{pages: CaptionPage[]; shift: boolean}> = ({pages, shift}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const page = pages.find((p) => t >= p.s && t < p.e);
  if (!page) return null;
  const local = frame - Math.round(page.s * fps);
  const pop = spring({frame: local, fps, config: {damping: 14, stiffness: 180}, durationInFrames: 10});
  return (
    <div
      style={{
        position: 'absolute', left: shift ? 90 : 160, right: shift ? 560 : 160, bottom: 120, display: 'flex', flexWrap: 'wrap',
        justifyContent: 'center', columnGap: 26, rowGap: 0, transform: `scale(${0.92 + 0.08 * pop})`,
      }}
    >
      {page.words.map((w, i) => {
        const active = t >= w.s - 0.03 && t < Math.max(w.e, w.s + 0.12);
        const done = t >= w.e;
        return (
          <span
            key={i}
            style={{
              fontFamily: BODY, fontWeight: 800, fontSize: 66, lineHeight: 1.18, textTransform: 'uppercase',
              color: active ? GOLD : done ? '#FFFFFF' : 'rgba(255,255,255,0.88)',
              transform: active ? 'translateY(-4px)' : 'none', display: 'inline-block', whiteSpace: 'nowrap',
              textShadow: OUTLINE,
            }}
          >
            {w.w}
          </span>
        );
      })}
    </div>
  );
};

/* -------------------------------------------------------------- headlines */

const HeadlineView: React.FC<{h: Headline}> = ({h}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const dur = Math.round((h.e - h.s) * fps);
  const inP = spring({frame: f, fps, config: {damping: 16}, durationInFrames: 14});
  const out = interpolate(f, [dur - 10, dur], [1, 0], clamp);
  return (
    <div style={{position: 'absolute', left: 90, top: 80, display: 'flex', alignItems: 'stretch', opacity: out}}>
      <div style={{width: 12, background: GOLD, transform: `scaleY(${inP})`, transformOrigin: 'top'}} />
      <div style={{overflow: 'hidden', marginLeft: 22}}>
        <div
          style={{
            fontFamily: HEAD, fontSize: 78, color: 'white', textTransform: 'uppercase', letterSpacing: 1,
            transform: `translateX(${(1 - inP) * -110}%)`, textShadow: '0 6px 24px rgba(0,0,0,0.7)', lineHeight: 1.1,
            padding: '4px 0',
          }}
        >
          {h.text}
        </div>
      </div>
    </div>
  );
};

/* ---------------------------------------------------------- chapter cards */

const ChapterCard: React.FC<{c: Chapter; frames: number}> = ({c, frames}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const inP = spring({frame: f, fps, config: {damping: 15}, durationInFrames: 16});
  const out = interpolate(f, [frames - 10, frames], [1, 0], clamp);
  return (
    <AbsoluteFill style={{opacity: out}}>
      <AbsoluteFill style={{background: 'radial-gradient(circle at 30% 50%, rgba(0,0,0,0.55), rgba(0,0,0,0.85))', opacity: inP}} />
      <AbsoluteFill style={{justifyContent: 'center', paddingLeft: 140}}>
        <div style={{fontFamily: BODY, fontWeight: 800, fontSize: 30, letterSpacing: 10, color: GOLD,
                     transform: `translateY(${(1 - inP) * 30}px)`, opacity: inP}}>
          CHAPTER {String(c.index).padStart(2, '0')}
        </div>
        <div style={{fontFamily: HEAD, fontSize: 150, color: 'white', textTransform: 'uppercase', lineHeight: 1,
                     marginTop: 12, transform: `translateX(${(1 - inP) * -60}px)`, opacity: inP,
                     textShadow: '0 10px 40px rgba(0,0,0,0.6)'}}>
          {c.name}
        </div>
        <div style={{height: 10, width: 260 * inP, background: GOLD, marginTop: 26}} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/* --------------------------------------------------------------- graphics */

function parseNumber(v: string): {pre: string; num: number; dec: number; post: string} | null {
  const m = String(v).match(/^([^0-9-]*)(-?[0-9][0-9,]*(?:\.[0-9]+)?)(.*)$/);
  if (!m) return null;
  const raw = m[2].replace(/,/g, '');
  return {pre: m[1], num: parseFloat(raw), dec: (raw.split('.')[1] || '').length, post: m[3]};
}

const Panel: React.FC<{children: React.ReactNode; frames: number}> = ({children, frames}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const inP = spring({frame: f, fps, config: {damping: 15}, durationInFrames: 16});
  const out = interpolate(f, [frames - 10, frames], [1, 0], clamp);
  return (
    <AbsoluteFill style={{opacity: out}}>
      <AbsoluteFill style={{background: 'rgba(5,5,6,0.62)', opacity: inP}} />
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', transform: `scale(${0.9 + 0.1 * inP})`, opacity: inP}}>
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const StatGraphic: React.FC<{g: Extract<Graphic, {type: 'stat'}>; frames: number}> = ({g, frames}) => {
  const f = useCurrentFrame();
  const n = parseNumber(g.value);
  const p = interpolate(f, [6, 40], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const shown = n ? `${n.pre}${(n.num * p).toLocaleString('en-US', {minimumFractionDigits: n.dec, maximumFractionDigits: n.dec})}${n.post}` : g.value;
  return (
    <Panel frames={frames}>
      <div style={{fontFamily: HEAD, fontSize: 230, color: GOLD, lineHeight: 1, textShadow: '0 12px 50px rgba(0,0,0,0.6)'}}>{shown}</div>
      <div style={{fontFamily: BODY, fontWeight: 800, fontSize: 48, color: 'white', marginTop: 24, textTransform: 'uppercase',
                   maxWidth: 1400, textAlign: 'center', letterSpacing: 2}}>{g.label}</div>
    </Panel>
  );
};

export const TimelineGraphic: React.FC<{g: Extract<Graphic, {type: 'timeline'}>; frames: number}> = ({g, frames}) => {
  const f = useCurrentFrame();
  const items = [...g.history.slice(-3), {year: g.year, label: g.label}];
  const line = interpolate(f, [4, 26], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const W = 1500;
  return (
    <Panel frames={frames}>
      <div style={{position: 'relative', width: W, height: 420}}>
        <div style={{position: 'absolute', top: 200, left: 0, height: 6, width: W * line, background: 'rgba(255,255,255,0.35)'}} />
        {items.map((it, i) => {
          const x = items.length === 1 ? W / 2 : (W * i) / (items.length - 1);
          const last = i === items.length - 1;
          const appear = interpolate(f, [8 + i * 5, 18 + i * 5], [0, 1], clamp);
          return (
            <div key={i} style={{position: 'absolute', left: x - 170, width: 340, top: 0, height: 420, opacity: last ? appear : appear * 0.55,
                                 display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
              <div style={{fontFamily: HEAD, fontSize: last ? 120 : 80, color: last ? GOLD : 'white', height: 160,
                           display: 'flex', alignItems: 'flex-end'}}>{it.year}</div>
              <div style={{width: last ? 40 : 26, height: last ? 40 : 26, borderRadius: 999, background: last ? GOLD : 'white',
                           marginTop: last ? 20 : 27, boxShadow: last ? `0 0 30px ${GOLD}` : undefined}} />
              <div style={{fontFamily: BODY, fontWeight: 700, fontSize: last ? 34 : 26, color: 'white', textAlign: 'center', marginTop: 24,
                           lineHeight: 1.25}}>{it.label}</div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
};

export const CompareGraphic: React.FC<{g: Extract<Graphic, {type: 'compare'}>; frames: number}> = ({g, frames}) => {
  const f = useCurrentFrame();
  const max = Math.max(g.a.value, g.b.value) || 1;
  const grow = (i: number) => interpolate(f, [8 + i * 6, 40 + i * 6], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const row = (side: {label: string; value: number}, i: number, color: string) => (
    <div style={{display: 'flex', alignItems: 'center', marginTop: i ? 50 : 0}}>
      <div style={{fontFamily: HEAD, fontSize: 70, color: 'white', width: 380, textAlign: 'right', marginRight: 36, textTransform: 'uppercase'}}>{side.label}</div>
      <div style={{height: 96, width: 900 * (side.value / max) * grow(i), background: color, borderRadius: 8}} />
      <div style={{fontFamily: HEAD, fontSize: 70, color, marginLeft: 28}}>
        {(side.value * grow(i)).toLocaleString('en-US', {maximumFractionDigits: 1})}{g.unit}
      </div>
    </div>
  );
  return (
    <Panel frames={frames}>
      <div style={{fontFamily: BODY, fontWeight: 800, fontSize: 40, color: GOLD, letterSpacing: 6, textTransform: 'uppercase', marginBottom: 60}}>{g.title}</div>
      <div>{row(g.a, 0, GOLD)}{row(g.b, 1, '#E8E8E8')}</div>
    </Panel>
  );
};

export const ChartGraphic: React.FC<{g: Extract<Graphic, {type: 'chart'}>; frames: number}> = ({g, frames}) => {
  const f = useCurrentFrame();
  const pts = g.points;
  const W = 1400;
  const H = 520;
  const ys = pts.map((p) => p[1]);
  const lo = Math.min(0, ...ys);
  const hi = Math.max(...ys) || 1;
  const X = (i: number) => (pts.length < 2 ? W / 2 : (W * i) / (pts.length - 1));
  const Y = (v: number) => H - ((v - lo) / (hi - lo || 1)) * H;
  const prog = interpolate(f, [6, Math.min(frames - 20, 70)], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
  const n = Math.max(1, Math.floor(prog * (pts.length - 1)));
  const shown = pts.slice(0, n + 1);
  const d = shown.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ');
  const last = shown[shown.length - 1];
  const val = (v: number) => `${g.prefix}${v.toLocaleString('en-US', {maximumFractionDigits: Math.abs(v) < 10 ? 1 : 0})}${g.unit}`;
  return (
    <Panel frames={frames}>
      <div style={{fontFamily: BODY, fontWeight: 800, fontSize: 40, color: GOLD, letterSpacing: 5, textTransform: 'uppercase', marginBottom: 40}}>{g.title}</div>
      <svg width={W + 260} height={H + 90} style={{overflow: 'visible'}}>
        <g transform="translate(40,20)">
          {lo < 0 ? <line x1={0} x2={W} y1={Y(0)} y2={Y(0)} stroke="rgba(255,255,255,0.35)" strokeDasharray="8 8" strokeWidth={3} /> : null}
          <line x1={0} x2={W} y1={H} y2={H} stroke="rgba(255,255,255,0.35)" strokeWidth={3} />
          <path d={`${d} L${X(n).toFixed(1)},${H} L0,${H} Z`} fill="rgba(212,175,55,0.16)" />
          <path d={d} fill="none" stroke={GOLD} strokeWidth={9} strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={X(n)} cy={Y(last[1])} r={16} fill={GOLD} />
          <text x={X(n) + 26} y={Y(last[1]) + 18} fill="white" style={{fontFamily: HEAD, fontSize: 64}}>{val(last[1])}</text>
          <text x={0} y={H + 62} fill="rgba(255,255,255,0.8)" style={{fontFamily: BODY, fontWeight: 700, fontSize: 34}}>{pts[0][0]}</text>
          <text x={X(n)} y={H + 62} textAnchor="middle" fill="rgba(255,255,255,0.8)" style={{fontFamily: BODY, fontWeight: 700, fontSize: 34}}>{last[0]}</text>
        </g>
      </svg>
    </Panel>
  );
};

export const CompanyCardView: React.FC<{c: CompanyCard; frames: number}> = ({c, frames}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const inP = spring({frame: f, fps, config: {damping: 15}, durationInFrames: 18});
  const out = interpolate(f, [frames - 12, frames], [1, 0], clamp);
  return (
    <AbsoluteFill style={{opacity: out}}>
      <AbsoluteFill style={{background: 'rgba(6,7,10,0.86)', opacity: inP}} />
      <AbsoluteFill style={{flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 90,
                            transform: `scale(${0.92 + 0.08 * inP})`, opacity: inP}}>
        {c.flag ? (
          <div style={{width: 560, padding: 18, background: 'white', borderRadius: 18, boxShadow: '0 30px 80px rgba(0,0,0,0.6)',
                       transform: `rotate(${(1 - inP) * -8 - 2}deg)`}}>
            <Img src={staticFile(c.flag)} style={{width: '100%', display: 'block', borderRadius: 6}} />
          </div>
        ) : null}
        <div style={{minWidth: 760}}>
          <div style={{fontFamily: BODY, fontWeight: 800, fontSize: 28, letterSpacing: 10, color: GOLD}}>COMPANY PROFILE</div>
          <div style={{fontFamily: HEAD, fontSize: 120, color: 'white', textTransform: 'uppercase', lineHeight: 1.05, marginTop: 6}}>{c.name}</div>
          <div style={{height: 8, width: 220, background: GOLD, margin: '18px 0 26px'}} />
          {c.rows.map(([k, v], i) => {
            const a = interpolate(f, [12 + i * 6, 22 + i * 6], [0, 1], clamp);
            return (
              <div key={i} style={{display: 'flex', alignItems: 'baseline', gap: 26, opacity: a, transform: `translateX(${(1 - a) * 40}px)`,
                                   borderBottom: '2px solid rgba(255,255,255,0.12)', padding: '10px 0'}}>
                <div style={{fontFamily: BODY, fontWeight: 800, fontSize: 30, color: GOLD, width: 230, letterSpacing: 3}}>{k}</div>
                <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 42, color: 'white'}}>{v}</div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/* ----------------------------------------------------------------- mascot */

const REACT = new Set(['shocked', 'laughing', 'facepalm', 'money', 'thumbsup']);

export const activeAppearance = (c: CharacterProps | null | undefined, t: number): Appearance | undefined =>
  c ? c.appearances.find((a) => t >= a.s && t < a.e) : undefined;

export const Mascot: React.FC<{c: CharacterProps; size?: number}> = ({c, size}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const a = activeAppearance(c, t);
  if (!a) return null;
  const pose = c.poses[a.pose] || c.poses[Object.keys(c.poses)[0]];
  if (!pose) return null;
  const local = frame - Math.round(a.s * fps);
  const remain = Math.round(a.e * fps) - frame;
  const inP = a.enter ? spring({frame: local, fps, config: {damping: 12, stiffness: 150}, durationInFrames: 18}) : 1;
  const outP = a.exit ? interpolate(remain, [0, 9], [0, 1], clamp) : 1;
  const vis = Math.min(inP, outP);
  const lvl = Number(c.level[frame] || '0');
  const talking = lvl >= 3;
  const src = talking ? pose.open : pose.closed;
  const react = REACT.has(a.pose);
  const pop = react ? spring({frame: local, fps, config: {damping: 7, stiffness: 220}, durationInFrames: 14}) : 1;
  const breathe = Math.sin((frame / fps) * Math.PI * 2 * 0.5) * 4;
  const bob = breathe - (talking ? lvl * 1.4 : 0);
  const tilt = Math.sin((frame / fps) * 1.3) * 1.3 + (react ? (1 - pop) * -6 : 0);
  const H = size || 600;

  // speech bubble
  const bFrom = 10;
  const bLen = Math.round(2.6 * fps);
  const bLocal = local - bFrom;
  const bIn = a.bubble && bLocal >= 0 ? spring({frame: bLocal, fps, config: {damping: 11, stiffness: 200}, durationInFrames: 12}) : 0;
  const bOut = interpolate(bLocal, [bLen - 8, bLen], [1, 0], clamp);
  const bubble = a.bubble && bLocal >= 0 && bLocal < bLen ? bIn * bOut : 0;

  // name tag on the first appearance
  const tagP = a.tag ? spring({frame: local - 12, fps, config: {damping: 15}, durationInFrames: 16}) *
    interpolate(local, [Math.round(3.6 * fps), Math.round(4.0 * fps)], [1, 0], clamp) : 0;

  return (
    <div style={{position: 'absolute', right: 20, bottom: 0, height: H, width: H * 0.93, pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute', right: 0, bottom: 0, height: H, display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-end',
          transform: `translateY(${(1 - vis) * 105}%) translateY(${bob}px) rotate(${tilt}deg) scale(${0.94 + 0.06 * pop})`,
          transformOrigin: 'bottom center',
        }}
      >
        <Img src={staticFile(src)} style={{height: H, maxWidth: 620, objectFit: 'contain', filter: 'drop-shadow(0 12px 28px rgba(0,0,0,0.7))'}} />
      </div>
      {bubble > 0 ? (
        <div
          style={{
            position: 'absolute', right: 330, bottom: H - 40, maxWidth: 440, background: 'white', color: '#0b0b0c',
            border: '5px solid #0b0b0c', borderRadius: 28, padding: '18px 26px', fontFamily: BODY, fontWeight: 800,
            fontSize: 40, lineHeight: 1.15, textAlign: 'center', boxShadow: '0 12px 30px rgba(0,0,0,0.45)',
            transform: `scale(${bubble})`, transformOrigin: '85% 100%', opacity: Math.min(1, bubble * 1.4),
          }}
        >
          {a.bubble}
          <div style={{position: 'absolute', right: 34, bottom: -26, width: 0, height: 0, borderLeft: '18px solid transparent',
                       borderRight: '18px solid transparent', borderTop: '26px solid #0b0b0c'}} />
        </div>
      ) : null}
      {tagP > 0 ? (
        <div style={{position: 'absolute', right: 400, bottom: 150, opacity: tagP, transform: `translateX(${(1 - tagP) * 40}px)`}}>
          <div style={{background: GOLD, color: '#0b0b0c', fontFamily: HEAD, fontSize: 54, padding: '4px 22px', letterSpacing: 2,
                       textTransform: 'uppercase'}}>{c.name}</div>
          <div style={{background: 'rgba(0,0,0,0.85)', color: 'white', fontFamily: BODY, fontWeight: 700, fontSize: 24,
                       padding: '6px 22px', whiteSpace: 'nowrap'}}>YOUR BUSINESS ANALYST</div>
        </div>
      ) : null}
    </div>
  );
};

/* ------------------------------------------------------------- chrome UI */

const ProgressBar: React.FC<{total: number; chapters: Chapter[]}> = ({total, chapters}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = Math.min(1, frame / fps / total);
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 8, background: 'rgba(255,255,255,0.15)'}}>
      <div style={{height: '100%', width: `${p * 100}%`, background: GOLD}} />
      {chapters.slice(1).map((c, i) => (
        <div key={i} style={{position: 'absolute', top: 0, bottom: 0, width: 4, left: `${(c.s / total) * 100}%`, background: '#000'}} />
      ))}
    </div>
  );
};

const Outro: React.FC<{channel: string}> = ({channel}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const inP = spring({frame: f, fps, config: {damping: 14}, durationInFrames: 18});
  return (
    <AbsoluteFill style={{background: `rgba(0,0,0,${0.85 * inP})`, justifyContent: 'center', alignItems: 'center'}}>
      <div style={{fontFamily: HEAD, fontSize: 170, color: GOLD, transform: `scale(${0.8 + 0.2 * inP})`, opacity: inP}}>SUBSCRIBE</div>
      <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 46, color: 'white', opacity: inP, marginTop: 10}}>
        for more business case studies{channel ? ` · ${channel}` : ''}
      </div>
    </AbsoluteFill>
  );
};

/* ------------------------------------------------------------------- main */

export const Main: React.FC<VideoProps> = (props) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const F = (s: number) => Math.round(s * fps);

  // punch-in zoom on emphasis moments
  let punch = 1;
  for (const p of props.punches) {
    const d = t - p;
    if (d >= 0 && d < 0.9) punch = Math.max(punch, 1 + 0.07 * interpolate(d, [0, 0.12, 0.9], [0, 1, 0], clamp));
  }

  // music ducking: quiet under the voice, a bit louder in pauses
  const musicVol = (f: number) => {
    const s = f / fps;
    const talking = props.speech.some(([a, b]) => s >= a - 0.15 && s <= b + 0.25);
    const fadeOut = interpolate(s, [props.total - 3, props.total], [1, 0], clamp);
    const fadeIn = interpolate(s, [0, 1.5], [0, 1], clamp);
    return (talking ? props.duckVolume : props.musicVolume) * fadeIn * fadeOut;
  };

  return (
    <AbsoluteFill style={{background: '#000'}}>
      <AbsoluteFill style={{transform: `scale(${punch})`}}>
        {props.shots.map((sh, i) => {
          const from = Math.max(0, F(sh.start) - (i > 0 && sh.transition !== 'cut' && sh.transition !== 'flash' ? OVERLAP : 0));
          const dur = Math.max(1, F(sh.end) - from);
          return (
            <Sequence key={i} from={from} durationInFrames={dur} layout="none">
              <AbsoluteFill>
                <ShotView shot={sh} frames={dur} first={i === 0} />
              </AbsoluteFill>
            </Sequence>
          );
        })}
      </AbsoluteFill>

      {props.shots.map((sh, i) =>
        i > 0 && sh.transition === 'flash' ? (
          <Sequence key={`fl${i}`} from={Math.max(0, F(sh.start) - 2)} durationInFrames={8}>
            <Flash />
          </Sequence>
        ) : null,
      )}

      {/* legibility shading */}
      <AbsoluteFill style={{background: 'linear-gradient(to bottom, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 28%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.75) 100%)'}} />
      <AbsoluteFill style={{boxShadow: 'inset 0 0 220px rgba(0,0,0,0.65)'}} />

      {props.headlines.map((h, i) => (
        <Sequence key={`h${i}`} from={F(h.s)} durationInFrames={Math.max(1, F(h.e) - F(h.s))}>
          <HeadlineView h={h} />
        </Sequence>
      ))}

      {props.graphics.map((g, i) => {
        const frames = Math.max(1, F(g.e) - F(g.s));
        return (
          <Sequence key={`g${i}`} from={F(g.s)} durationInFrames={frames}>
            {g.type === 'stat' ? <StatGraphic g={g} frames={frames} /> : null}
            {g.type === 'timeline' ? <TimelineGraphic g={g} frames={frames} /> : null}
            {g.type === 'compare' ? <CompareGraphic g={g} frames={frames} /> : null}
            {g.type === 'chart' ? <ChartGraphic g={g} frames={frames} /> : null}
            {g.type === 'map' ? <MapScene g={g} frames={frames} /> : null}
          </Sequence>
        );
      })}

      {props.card ? (
        <Sequence from={F(props.card.s)} durationInFrames={Math.max(1, F(props.card.e) - F(props.card.s))}>
          <CompanyCardView c={props.card} frames={Math.max(1, F(props.card.e) - F(props.card.s))} />
        </Sequence>
      ) : null}

      {props.chapters.slice(1).map((c, i) => (
        <Sequence key={`c${i}`} from={F(c.s)} durationInFrames={F(2.2)}>
          <ChapterCard c={c} frames={F(2.2)} />
        </Sequence>
      ))}

      {props.character ? <Mascot c={props.character} /> : null}

      <Captions pages={props.pages} shift={!!activeAppearance(props.character, t)} />

      {props.channel ? (
        <div style={{position: 'absolute', right: 56, top: 44, fontFamily: BODY, fontWeight: 800, fontSize: 30, color: GOLD, opacity: 0.75,
                     letterSpacing: 2}}>{props.channel}</div>
      ) : null}

      <ProgressBar total={props.total} chapters={props.chapters} />

      <Sequence from={F(props.outroStart)}>
        <Outro channel={props.channel} />
      </Sequence>

      {/* audio */}
      {props.narration ? <Audio src={staticFile(props.narration)} /> : null}
      {props.music ? <Audio src={staticFile(props.music)} loop volume={musicVol} /> : null}
      {props.sfx.map((s, i) => (
        <Sequence key={`s${i}`} from={Math.max(0, F(s.at))} durationInFrames={F(1.2)}>
          <Audio src={staticFile(s.src)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

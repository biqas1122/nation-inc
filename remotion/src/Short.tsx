import React from 'react';
import {AbsoluteFill, Audio, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {
  BODY, ChartGraphic, CompareGraphic, Flash, GOLD, HEAD, Mascot, OUTLINE, OVERLAP, ShotView, StatGraphic, TimelineGraphic, clamp,
} from './Main';
import type {CaptionPage, ShortProps} from './types';
import {MapScene} from './MapScene';

/* Vertical 1080x1920 clip for YouTube Shorts / TikTok / Reels / Facebook. */

const ShortCaptions: React.FC<{pages: CaptionPage[]}> = ({pages}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const page = pages.find((p) => t >= p.s && t < p.e);
  if (!page) return null;
  const pop = spring({frame: frame - Math.round(page.s * fps), fps, config: {damping: 13, stiffness: 190}, durationInFrames: 9});
  return (
    <div style={{position: 'absolute', left: 60, right: 60, top: 1080, display: 'flex', flexWrap: 'wrap', justifyContent: 'center',
                 columnGap: 22, transform: `scale(${0.9 + 0.1 * pop})`}}>
      {page.words.map((w, i) => {
        const active = t >= w.s - 0.03 && t < Math.max(w.e, w.s + 0.12);
        return (
          <span key={i} style={{fontFamily: BODY, fontWeight: 800, fontSize: 84, lineHeight: 1.15, textTransform: 'uppercase',
                                color: active ? GOLD : 'white', textShadow: OUTLINE, whiteSpace: 'nowrap',
                                transform: active ? 'scale(1.08)' : 'none', display: 'inline-block'}}>
            {w.w}
          </span>
        );
      })}
    </div>
  );
};

const Hook: React.FC<{text: string}> = ({text}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const inP = spring({frame: f, fps, config: {damping: 14}, durationInFrames: 14});
  return (
    <div style={{position: 'absolute', top: 150, left: 60, right: 60, display: 'flex', justifyContent: 'center',
                 transform: `translateY(${(1 - inP) * -60}px)`, opacity: inP}}>
      <div style={{background: 'rgba(0,0,0,0.82)', borderBottom: `10px solid ${GOLD}`, padding: '22px 34px', maxWidth: 960,
                   fontFamily: HEAD, fontSize: 74, lineHeight: 1.08, color: 'white', textAlign: 'center', textTransform: 'uppercase'}}>
        {text}
      </div>
    </div>
  );
};

const Cta: React.FC<{text: string}> = ({text}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const inP = spring({frame: f, fps, config: {damping: 12}, durationInFrames: 12});
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', background: `rgba(0,0,0,${0.55 * inP})`}}>
      <div style={{fontFamily: HEAD, fontSize: 96, color: GOLD, textAlign: 'center', padding: '0 80px', lineHeight: 1.05,
                   transform: `scale(${0.85 + 0.15 * inP})`, opacity: inP, textShadow: OUTLINE}}>{text}</div>
    </AbsoluteFill>
  );
};

export const Short: React.FC<ShortProps> = (props) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const F = (s: number) => Math.round(s * fps);
  let punch = 1;
  for (const p of props.punches) {
    const d = t - p;
    if (d >= 0 && d < 0.9) punch = Math.max(punch, 1 + 0.07 * interpolate(d, [0, 0.12, 0.9], [0, 1, 0], clamp));
  }
  const musicVol = (f: number) => {
    const s = f / fps;
    const talking = props.speech.some(([a, b]) => s >= a - 0.15 && s <= b + 0.25);
    return (talking ? props.duckVolume : props.musicVolume) * interpolate(s, [props.total - 1, props.total], [1, 0], clamp);
  };
  return (
    <AbsoluteFill style={{background: '#000'}}>
      <AbsoluteFill style={{transform: `scale(${punch})`}}>
        {props.shots.map((sh, i) => {
          const from = Math.max(0, F(sh.start) - (i > 0 && sh.transition !== 'cut' && sh.transition !== 'flash' ? OVERLAP : 0));
          const dur = Math.max(1, F(sh.end) - from);
          return (
            <Sequence key={i} from={from} durationInFrames={dur} layout="none">
              <AbsoluteFill><ShotView shot={sh} frames={dur} first={i === 0} /></AbsoluteFill>
            </Sequence>
          );
        })}
      </AbsoluteFill>
      {props.shots.map((sh, i) => i > 0 && sh.transition === 'flash' ? (
        <Sequence key={`fl${i}`} from={Math.max(0, F(sh.start) - 2)} durationInFrames={8}><Flash /></Sequence>
      ) : null)}
      <AbsoluteFill style={{background: 'linear-gradient(to bottom, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0) 25%, rgba(0,0,0,0) 45%, rgba(0,0,0,0.7) 100%)'}} />

      {props.graphics.map((g, i) => {
        const frames = Math.max(1, F(g.e) - F(g.s));
        return (
          <Sequence key={`g${i}`} from={F(g.s)} durationInFrames={frames}>
            {g.type === 'map' ? (
              <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
                <div style={{width: 1920, height: 1080, transform: 'scale(0.5625)', flexShrink: 0}}><MapScene g={g} frames={frames} /></div>
              </AbsoluteFill>
            ) : null}
            <AbsoluteFill style={{transform: 'scale(0.68)', display: g.type === 'map' ? 'none' : undefined}}>
              {g.type === 'stat' ? <StatGraphic g={g} frames={frames} /> : null}
              {g.type === 'timeline' ? <TimelineGraphic g={g} frames={frames} /> : null}
              {g.type === 'compare' ? <CompareGraphic g={g} frames={frames} /> : null}
              {g.type === 'chart' ? <ChartGraphic g={g} frames={frames} /> : null}
            </AbsoluteFill>
          </Sequence>
        );
      })}

      {props.hook ? <Hook text={props.hook} /> : null}
      {props.character ? <Mascot c={props.character} size={520} /> : null}
      <ShortCaptions pages={props.pages} />

      <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 10, background: 'rgba(255,255,255,0.15)'}}>
        <div style={{height: '100%', width: `${Math.min(1, t / props.total) * 100}%`, background: GOLD}} />
      </div>
      {props.cta ? (
        <Sequence from={Math.max(0, F(props.total - 1.6))}><Cta text={props.cta} /></Sequence>
      ) : null}

      {props.narration ? <Audio src={staticFile(props.narration)} trimBefore={F(props.offset)} /> : null}
      {props.music ? <Audio src={staticFile(props.music)} loop volume={musicVol} /> : null}
      {props.sfx.map((s, i) => (
        <Sequence key={`s${i}`} from={Math.max(0, F(s.at))} durationInFrames={F(1.2)}>
          <Audio src={staticFile(s.src)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

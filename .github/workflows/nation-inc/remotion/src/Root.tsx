import React from 'react';
import {Composition} from 'remotion';
import {Main} from './Main';
import {Short} from './Short';
import type {VideoProps} from './types';

const defaults: VideoProps = {
  character: null,
  fps: 30,
  durationInFrames: 150,
  channel: 'Channel',
  narration: '',
  music: null,
  musicVolume: 0.14,
  duckVolume: 0.05,
  speech: [],
  shots: [],
  pages: [],
  headlines: [],
  chapters: [],
  graphics: [],
  punches: [],
  sfx: [],
  outroStart: 1,
  total: 5,
};

export const Root: React.FC = () => (
  <>
  <Composition
    id="Main"
    component={Main as unknown as React.FC<Record<string, unknown>>}
    width={1920}
    height={1080}
    fps={30}
    durationInFrames={150}
    defaultProps={defaults as unknown as Record<string, unknown>}
    calculateMetadata={({props}) => {
      const p = props as unknown as VideoProps;
      return {durationInFrames: Math.max(30, p.durationInFrames), fps: p.fps || 30};
    }}
  />
  <Composition
    id="Short"
    component={Short as unknown as React.FC<Record<string, unknown>>}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={150}
    defaultProps={{...defaults, offset: 0, hook: '', cta: ''} as unknown as Record<string, unknown>}
    calculateMetadata={({props}) => {
      const p = props as unknown as VideoProps;
      return {durationInFrames: Math.max(30, p.durationInFrames), fps: p.fps || 30};
    }}
  />
  </>
);

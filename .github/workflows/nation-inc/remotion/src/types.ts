export type Shot = {
  src: string;               // path inside public/
  type: 'video' | 'photo';
  start: number;             // seconds
  end: number;               // seconds
  trim?: number;             // seconds to skip at the start of a video
  rate?: number;             // playback rate for videos
  motion: 'in' | 'out' | 'left' | 'right';
  transition: 'cut' | 'fade' | 'whip' | 'flash';
  credit?: string;           // shown small on screen (Wikimedia photos)
};

export type Word = {w: string; s: number; e: number};
export type CaptionPage = {s: number; e: number; words: Word[]};
export type Headline = {text: string; s: number; e: number};
export type Chapter = {name: string; s: number; index: number};

export type Graphic =
  | {type: 'stat'; s: number; e: number; value: string; label: string}
  | {type: 'timeline'; s: number; e: number; year: string; label: string; history: {year: string; label: string}[]}
  | {type: 'compare'; s: number; e: number; title: string; unit: string;
      a: {label: string; value: number}; b: {label: string; value: number}}
  | {type: 'chart'; s: number; e: number; title: string; prefix: string; unit: string; points: [number, number][]};

export type CompanyCard = {name: string; rows: [string, string][]; s: number; e: number; flag: string | null};

export type Sfx = {src: string; at: number; volume: number};

export type CharacterPose = {closed: string; open: string};
export type Appearance = {s: number; e: number; pose: string; bubble: string; enter: boolean; exit: boolean; tag: boolean};
export type CharacterProps = {
  name: string;
  poses: Record<string, CharacterPose>;
  appearances: Appearance[];
  level: string; // one digit 0-9 per frame: narrator loudness
};

export type VideoProps = {
  card?: CompanyCard | null;
  character?: CharacterProps | null;
  fps: number;
  durationInFrames: number;
  channel: string;
  narration: string;
  music: string | null;
  musicVolume: number;
  duckVolume: number;
  speech: [number, number][];
  shots: Shot[];
  pages: CaptionPage[];
  headlines: Headline[];
  chapters: Chapter[];
  graphics: Graphic[];
  punches: number[];
  sfx: Sfx[];
  outroStart: number;
  total: number;
};

export type ShortProps = VideoProps & {
  offset: number;      // where this clip starts inside the narration (s)
  hook: string;        // big text at the top
  cta: string;         // last-second call to action
};

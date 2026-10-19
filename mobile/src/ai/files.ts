/* Text from study material the student attaches: the desktop's ai/files.py on the phone. PDF (pdf.js), PowerPoint
   (.pptx), Word (.docx), text and Markdown, plus code files on the phone, where there's no code workspace.
   Everything happens on the phone; only the text goes with a question. Files are read defensively:
   - Word and PowerPoint files are zip archives of XML: sizes are checked before anything is unpacked, and XML
     with a DOCTYPE or ENTITY is refused.
   - PDFs are read page by page, up to a page and time limit. Password-protected ones are refused.
   - A file with no text at all (a scanned PDF) is reported, not sent empty. */
import { unzipSync } from 'fflate';

export const MAX_UPLOAD = 30 * 1024 * 1024;
const MAX_UNZIPPED = 80 * 1024 * 1024;
const MAX_MEMBER = 30 * 1024 * 1024;
const MAX_PARTS = 1000;
const MAX_TEXT = 2_000_000;
const SECTION = 4000;
const PDF_SECONDS = 60;
export const CLOUD_CHARS = 150_000;

const KINDS: Record<string, string> = { '.pdf': 'PDF', '.pptx': 'PowerPoint', '.docx': 'Word', '.txt': 'Text', '.md': 'Markdown', '.markdown': 'Markdown' };
/** Code is plain text: on the phone it's attached to a study chat (the desktop links whole folders instead). */
export const CODE_EXTENSIONS = ['.py', '.java', '.c', '.h', '.cpp', '.hpp', '.cc', '.cs', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs',
  '.kt', '.swift', '.rb', '.php', '.sql', '.html', '.css', '.json', '.xml', '.yaml', '.yml', '.sh', '.r', '.m', '.scala', '.dart'];
const OLD: Record<string, string> = { '.doc': 'Word 97-2003 (.doc)', '.ppt': 'PowerPoint 97-2003 (.ppt)', '.rtf': 'Rich Text (.rtf)',
  '.odt': 'OpenDocument (.odt)', '.pages': 'Pages', '.key': 'Keynote' };

export class FileError extends Error {}

export interface Part { label: string; text: string }
export interface Extracted { name: string; kind: string; parts: Part[]; chars: number; words: number }

/** Reads a PDF's pages: their text, or 'locked' when it's password-protected. Supplied by the app (pdf.js). */
export type PdfReader = (data: Uint8Array, deadline: number) => Promise<string[] | 'locked'>;

const ext = (name: string) => { const m = /\.[^./\\]+$/.exec(name); return m ? m[0].toLowerCase() : ''; };
const baseName = (name: string) => name.split(/[\\/]/).pop() || name;

export async function extract(name: string, data: Uint8Array, readPdf: PdfReader): Promise<Extracted> {
  const e = ext(name);
  if (data.length > MAX_UPLOAD) throw new FileError('That file is over 30 MB. Attach a smaller file, or just the part you need.');
  if (e in OLD) throw new FileError(`${OLD[e]} files can't be read. Save it as PDF, .docx or .pptx and attach that.`);
  const isCode = CODE_EXTENSIONS.includes(e);
  if (!(e in KINDS) && !isCode) throw new FileError('Attach a PDF, PowerPoint (.pptx), Word (.docx), text, Markdown or code file.');
  if (!data.length) throw new FileError('That file is empty.');
  let parts: Part[];
  if (e === '.pdf') parts = await pdf(data, readPdf);
  else if (e === '.pptx') parts = pptx(data);
  else if (e === '.docx') parts = sections(docx(data), 'Section');
  else parts = sections(decode(data), 'Section');
  parts = parts.filter(p => p.text.trim());
  if (!parts.length) {
    throw new FileError("There's no text in that file to read. If it's scanned pages (pictures), EasyUniTrack can't read them yet: " +
      'copy the text in, or use a version with real text.');
  }
  let total = 0;
  const kept: Part[] = [];
  for (const p of parts) {
    if (total >= MAX_TEXT) break;
    const text = p.text.slice(0, MAX_TEXT - total);
    total += text.length;
    kept.push({ ...p, text });
  }
  const all = kept.map(p => p.text).join(' ');
  return { name: baseName(name).slice(0, 200), kind: isCode ? 'Code' : KINDS[e], parts: kept, chars: total,
    words: all.split(/\s+/).filter(Boolean).length };
}

async function pdf(data: Uint8Array, readPdf: PdfReader): Promise<Part[]> {
  let pages: string[] | 'locked';
  try {
    pages = await readPdf(data, Date.now() + PDF_SECONDS * 1000);
  } catch (e) {
    if (e instanceof FileError) throw e;
    throw new FileError(`That PDF couldn't be read (${(e as Error)?.name || 'Error'}). It may be damaged.`);
  }
  if (pages === 'locked') {
    throw new FileError("That PDF is password-protected or locked, so its text can't be read. If it's your own file, save a copy " +
      'without the protection and attach that.');
  }
  return pages.slice(0, MAX_PARTS).map((text, i) => ({ label: `Page ${i + 1}`, text: tidy(text) }));
}

/** pdf.js page reading with the desktop's limits, for the app to pass in as its PdfReader. */
export function pdfJsReader(load: () => Promise<any>): PdfReader {
  return async (data, deadline) => {
    const pdfjs = await load();
    let doc: any;
    try {
      doc = await pdfjs.getDocument({ data: data.slice(), isEvalSupported: false, disableFontFace: true, useSystemFonts: false }).promise;
    } catch (e) {
      if ((e as Error)?.name === 'PasswordException') return 'locked';
      throw e;
    }
    try {
      const pages: string[] = [];
      for (let i = 1; i <= Math.min(doc.numPages, MAX_PARTS); i++) {
        if (Date.now() > deadline) {
          throw new FileError(`That PDF is taking too long to read (it got to page ${i - 1}). Save the pages you need as a smaller PDF and attach that.`);
        }
        try {
          const content = await (await doc.getPage(i)).getTextContent();
          pages.push(content.items.map((it: any) => (it.str ?? '') + (it.hasEOL ? '\n' : '')).join(''));
        } catch (e) {
          if (e instanceof FileError) throw e;
          pages.push('');                                // one damaged page doesn't stop the rest
        }
      }
      return pages;
    } finally {
      await doc.destroy?.();
    }
  };
}

// ── Word and PowerPoint (zip archives of XML) ──
function zip(data: Uint8Array): (member: string) => string | null {
  let total = 0;
  try {
    unzipSync(data, {
      filter: f => {
        if (f.originalSize > MAX_MEMBER) throw new FileError("That file has a part that's far too big to read safely.");
        total += f.originalSize;
        return false;                                    // sizes first: nothing is unpacked yet
      },
    });
  } catch (e) {
    if (e instanceof FileError) throw e;
    throw new FileError("That file couldn't be opened. It may be damaged, or not really that kind of file.");
  }
  if (total > MAX_UNZIPPED) throw new FileError('That file unpacks to far too much to read safely.');
  let files: Record<string, Uint8Array>;
  try {
    files = unzipSync(data, { filter: f => f.name.endsWith('.xml') || f.name.endsWith('.rels') });
  } catch {
    throw new FileError("Part of that file is damaged, so it couldn't be read.");
  }
  return member => {
    const raw = files[member];
    if (!raw) return null;
    const head = raw.subarray(0, 512);
    const text = new TextDecoder('utf-8').decode(raw);
    const upper = text.toUpperCase();
    if (head.includes(0) || upper.includes('<!DOCTYPE') || upper.includes('<!ENTITY')) {
      throw new FileError("That file contains XML EasyUniTrack won't read, for safety.");
    }
    return text;
  };
}

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
const unescapeXml = (s: string) => s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e: string) => {
  if (e[0] === '#') {
    const n = e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
    return Number.isFinite(n) && n <= 0x10ffff ? String.fromCodePoint(n) : m;
  }
  return ENTITIES[e] ?? m;
});

/** Each paragraph (<p:tag>…</p:tag>) as one line of its text runs. */
function paragraphs(xml: string, ns: string, withBreaks = false): string[] {
  const out: string[] = [];
  const para = new RegExp(`<${ns}:p\\b[^>]*?(?:/>|>([\\s\\S]*?)</${ns}:p>)`, 'g');
  const run = new RegExp(`<${ns}:t\\b[^>]*?(?:/>|>([\\s\\S]*?)</${ns}:t>)|<${ns}:(tab|br|cr)\\b[^>]*/>`, 'g');
  for (const p of xml.matchAll(para)) {
    let line = '';
    for (const r of (p[1] ?? '').matchAll(run)) {
      if (r[2] === 'tab') line += withBreaks ? '\t' : '';
      else if (r[2]) line += withBreaks ? '\n' : '';
      else line += unescapeXml(r[1] ?? '');
    }
    if (line.trim()) out.push(line.trim());
  }
  return out;
}

function docx(data: Uint8Array): string {
  const read = zip(data);
  const xml = read('word/document.xml');
  if (xml === null) throw new FileError("That doesn't look like a Word (.docx) file.");
  return paragraphs(xml, 'w', true).join('\n');
}

function pptx(data: Uint8Array): Part[] {
  const read = zip(data);
  const names: string[] = [];
  unzipSync(data, { filter: f => { if (/^ppt\/slides\/slide\d+\.xml$/.test(f.name)) names.push(f.name); return false; } });
  if (!names.length) throw new FileError("That doesn't look like a PowerPoint (.pptx) file.");
  const order = names.sort((a, b) => Number(/(\d+)\.xml$/.exec(a)![1]) - Number(/(\d+)\.xml$/.exec(b)![1]));
  return order.slice(0, MAX_PARTS).map((member, i) => {
    const xml = read(member);
    const lines = xml !== null ? paragraphs(xml, 'a') : [];
    const notes = slideNotes(read, member);
    return { label: `Slide ${i + 1}`, text: tidy(lines.join('\n') + (notes ? `\nSpeaker notes: ${notes}` : '')) };
  });
}

function slideNotes(read: (m: string) => string | null, slide: string): string {
  const rels = read(slide.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels');
  if (rels === null) return '';
  for (const rel of rels.matchAll(/<Relationship\b([^>]*)\/?>/g)) {
    const attrs = rel[1];
    const type = /\bType="([^"]*)"/.exec(attrs)?.[1] ?? '';
    if (!type.endsWith('/notesSlide')) continue;
    const target = unescapeXml(/\bTarget="([^"]*)"/.exec(attrs)?.[1] ?? '');
    const member = target.startsWith('../') ? 'ppt/' + target.slice(3) : target.replace(/^\/+/, '');
    const xml = read(member);
    if (xml !== null) return paragraphs(xml, 'a').filter(l => !/^\d+$/.test(l)).join(' ');   // not the slide number
  }
  return '';
}

// ── text ──
function decode(data: Uint8Array): string {
  if ((data[0] === 0xff && data[1] === 0xfe) || (data[0] === 0xfe && data[1] === 0xff)) {
    try { return new TextDecoder(data[0] === 0xff ? 'utf-16le' : 'utf-16be', { fatal: true }).decode(data); } catch { /* fall through */ }
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(data);       // drops a byte-order mark too
  } catch {
    return new TextDecoder('windows-1252').decode(data);
  }
}

/** Text without pages, in parts of about SECTION characters, split between paragraphs. */
function sections(text: string, label: string): Part[] {
  const parts: string[] = [];
  let current = '';
  for (const para of tidy(text).split('\n')) {
    if (current && current.length + para.length > SECTION) {
      parts.push(current);
      current = '';
    }
    current += (current ? '\n' : '') + para;
  }
  if (current) parts.push(current);
  return parts.slice(0, MAX_PARTS).map((p, i) => ({ label: `${label} ${i + 1}`, text: p }));
}

function tidy(text: string): string {
  return text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\x00/g, '')
    .replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}

/** How much attached text goes with one question (it's sent again with each one, and billed each time). */
export const budget = () => ({ chars: CLOUD_CHARS, slow_over: null, context: null });

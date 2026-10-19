/* Request validation that mirrors the desktop's Pydantic models: the same rules, the same 422 responses
   ({"detail": [{"loc": ["body", field], "msg": …}]}) and the same messages, which app.js shows to the student. */
import { HttpError } from './http';

type Loc = (string | number)[];
interface ErrorItem { type: string; loc: Loc; msg: string; input: unknown }

class Invalid extends Error {
  constructor(public type: string, public msg: string) { super(msg); }
}

export interface Rule {
  kind: 'str' | 'int' | 'float' | 'bool' | 'lit' | 'date' | 'list' | 'model' | 'dict';
  /** null is allowed (Optional[...]). */
  nullable?: boolean;
  /** No default: the field must be sent. */
  required?: boolean;
  default?: unknown;
  minLen?: number; maxLen?: number; pattern?: string;
  ge?: number; gt?: number; le?: number;
  values?: readonly (string | number)[];
  item?: Rule; maxItems?: number; minItems?: number;
  model?: Model;
  /** Runs after the type check, like a Pydantic field_validator (throw ValueError-style messages). */
  check?: (v: any) => any;
}

export type Model = Record<string, Rule>;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;
const quoteList = (vals: readonly (string | number)[]) => {
  const q = vals.map(v => (typeof v === 'number' ? String(v) : `'${v}'`));
  return q.length > 1 ? `${q.slice(0, -1).join(', ')} or ${q[q.length - 1]}` : q[0];
};

const TRUE = new Set(['1', 'on', 't', 'true', 'y', 'yes']);
const FALSE = new Set(['0', 'off', 'f', 'false', 'n', 'no']);

function num(v: unknown, kind: 'int' | 'float'): number {
  const what = kind === 'int' ? 'integer' : 'number';
  if (typeof v === 'boolean') return v ? 1 : 0;
  if (typeof v === 'number') {
    if (!Number.isFinite(v) && kind === 'int') throw new Invalid('finite_number', 'Input should be a finite number');
    if (kind === 'int' && !Number.isInteger(v)) throw new Invalid('int_from_float', 'Input should be a valid integer, got a number with a fractional part');
    return v;
  }
  if (typeof v === 'string') {
    const s = v.trim();
    const ok = kind === 'int' ? /^[+-]?\d+$/.test(s) : /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s);
    if (!ok) throw new Invalid(`${kind}_parsing`, `Input should be a valid ${what}, unable to parse string as ${kind === 'int' ? 'an integer' : 'a number'}`);
    return Number(s);
  }
  throw new Invalid(`${kind}_type`, `Input should be a valid ${what}`);
}

function one(rule: Rule, v: unknown, loc: Loc, errors: ErrorItem[]): unknown {
  if (v === null && rule.nullable) return null;
  try {
    let out: any;
    switch (rule.kind) {
      case 'date':                       // a "before" validator: it sees the raw value first
        out = rule.check!(v);
        if (out === null && !rule.nullable) throw new Invalid('string_type', 'Input should be a valid string');
        return out;
      case 'str':
        if (typeof v !== 'string') throw new Invalid('string_type', 'Input should be a valid string');
        out = v;
        if (rule.minLen !== undefined && [...out].length < rule.minLen) {
          throw new Invalid('string_too_short', `String should have at least ${plural(rule.minLen, 'character')}`);
        }
        if (rule.maxLen !== undefined && [...out].length > rule.maxLen) {
          throw new Invalid('string_too_long', `String should have at most ${plural(rule.maxLen, 'character')}`);
        }
        if (rule.pattern !== undefined && !new RegExp(rule.pattern).test(out)) {
          throw new Invalid('string_pattern_mismatch', `String should match pattern '${rule.pattern}'`);
        }
        break;
      case 'int':
      case 'float':
        out = num(v, rule.kind);
        if (rule.gt !== undefined && !(out > rule.gt)) throw new Invalid('greater_than', `Input should be greater than ${rule.gt}`);
        if (rule.ge !== undefined && !(out >= rule.ge)) throw new Invalid('greater_than_equal', `Input should be greater than or equal to ${rule.ge}`);
        if (rule.le !== undefined && !(out <= rule.le)) throw new Invalid('less_than_equal', `Input should be less than or equal to ${rule.le}`);
        break;
      case 'bool':
        if (typeof v === 'boolean') out = v;
        else if (v === 0 || v === 1) out = v === 1;
        else if (typeof v === 'string' && TRUE.has(v.trim().toLowerCase())) out = true;
        else if (typeof v === 'string' && FALSE.has(v.trim().toLowerCase())) out = false;
        else throw new Invalid('bool_parsing', 'Input should be a valid boolean, unable to interpret input');
        break;
      case 'lit':
        if ((typeof v !== 'string' && typeof v !== 'number') || !rule.values!.includes(v)) {
          throw new Invalid('literal_error', `Input should be ${quoteList(rule.values!)}`);
        }
        out = v;
        break;
      case 'list': {
        if (!Array.isArray(v)) throw new Invalid('list_type', 'Input should be a valid list');
        if (rule.minItems !== undefined && v.length < rule.minItems) {
          throw new Invalid('too_short', `List should have at least ${plural(rule.minItems, 'item')} after validation, not ${v.length}`);
        }
        if (rule.maxItems !== undefined && v.length > rule.maxItems) {
          throw new Invalid('too_long', `List should have at most ${plural(rule.maxItems, 'item')} after validation, not ${v.length}`);
        }
        out = v.map((x, i) => one(rule.item!, x, [...loc, i], errors));
        return out;
      }
      case 'model':
        return parseInto(rule.model!, v, loc, errors).data;
      case 'dict':
        if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Invalid('dict_type', 'Input should be a valid dictionary');
        out = v;
        break;
    }
    if (rule.check) out = rule.check(out);
    return out;
  } catch (e) {
    if (e instanceof Invalid) errors.push({ type: e.type, loc, msg: e.msg, input: v });
    else if (e instanceof ValueError) errors.push({ type: 'value_error', loc, msg: `Value error, ${e.message}`, input: v });
    else throw e;
    return undefined;
  }
}

/** Raised by a check, like Python's ValueError in a validator. */
export class ValueError extends Error {}

function parseInto(model: Model, input: unknown, loc: Loc, errors: ErrorItem[]) {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) {
    errors.push({ type: 'model_attributes_type', loc, msg: 'Input should be a valid dictionary or object to extract fields from', input });
    return { data: {} as Record<string, any>, set: new Set<string>() };
  }
  const src = input as Record<string, unknown>;
  const data: Record<string, any> = {};
  const set = new Set<string>();
  for (const [name, rule] of Object.entries(model)) {
    if (Object.prototype.hasOwnProperty.call(src, name)) {
      set.add(name);
      data[name] = one(rule, src[name], [...loc, name], errors);
    } else if (rule.required) {
      errors.push({ type: 'missing', loc: [...loc, name], msg: 'Field required', input });
    } else {
      data[name] = rule.default === undefined ? null : rule.default;
    }
  }
  return { data, set };
}

/** Validate a request body. Returns every field (defaults filled in) and which ones were sent (exclude_unset). */
export function parse<T = Record<string, any>>(model: Model, input: unknown): { data: T; set: Set<string> } {
  const errors: ErrorItem[] = [];
  const out = parseInto(model, input, ['body'], errors);
  if (errors.length) throw new HttpError(422, errors);
  return out as { data: T; set: Set<string> };
}

/** Just the fields that were sent (model_dump(exclude_unset=True)). */
export function sent<T = Record<string, any>>(model: Model, input: unknown): T {
  const { data, set } = parse(model, input);
  const out: Record<string, any> = {};
  for (const k of set) out[k] = data[k];
  return out as T;
}

// ── Rule shorthands ──
export const str = (o: Partial<Rule> = {}): Rule => ({ kind: 'str', default: '', ...o });
export const optStr = (o: Partial<Rule> = {}): Rule => ({ kind: 'str', nullable: true, default: null, ...o });
export const name = (o: Partial<Rule> = {}): Rule => ({ kind: 'str', required: true, minLen: 1, maxLen: 120, ...o });
export const lit = (values: readonly (string | number)[], o: Partial<Rule> = {}): Rule => ({ kind: 'lit', values, ...o });
export const int = (o: Partial<Rule> = {}): Rule => ({ kind: 'int', ...o });
export const optInt = (o: Partial<Rule> = {}): Rule => ({ kind: 'int', nullable: true, default: null, ...o });
export const float = (o: Partial<Rule> = {}): Rule => ({ kind: 'float', ...o });
export const optFloat = (o: Partial<Rule> = {}): Rule => ({ kind: 'float', nullable: true, default: null, ...o });
export const bool = (o: Partial<Rule> = {}): Rule => ({ kind: 'bool', ...o });
export const HEX = '^#[0-9a-fA-F]{6}$';
export const hexColor = (o: Partial<Rule> = {}): Rule => ({ kind: 'str', default: '#2f5d50', pattern: HEX, ...o });

/** Python's date.fromisoformat (3.11+) for the forms students send: YYYY-MM-DD and YYYYMMDD. */
export function isoDate(v: unknown): string | null {
  if (v === null || v === undefined || v === '') return null;
  if (typeof v === 'string') {
    const m = /^(\d{4})-?(\d{2})-?(\d{2})$/.exec(v);
    if (m && (v.length === 10 ? v[4] === '-' && v[7] === '-' : v.length === 8)) {
      const [y, mo, d] = [+m[1], +m[2], +m[3]];
      const dt = new Date(Date.UTC(y, mo - 1, d));
      if (y >= 1 && dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d) {
        return `${m[1]}-${m[2]}-${m[3]}`;
      }
    }
  }
  throw new ValueError('Use a date in YYYY-MM-DD format');
}

/** A date field (DatesMixin): "" and null become null, anything else must be a real date. */
export const date = (o: Partial<Rule> = {}): Rule => ({ kind: 'date', nullable: true, default: null, check: isoDate, ...o });

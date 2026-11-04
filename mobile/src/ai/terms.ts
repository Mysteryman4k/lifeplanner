/* Terms of use for the AI features on the phone: the desktop's ai/terms.py, with what differs on a phone
   (the key is kept in the phone's secure storage; there's no code workspace that runs programs or changes files).
   The agreement is stored only on this phone and isn't in backups. Changing TERMS_VERSION asks again. */

export const TERMS_VERSION = '1.0-phone';

const ABOUT: [string, string][] = [
  ['It can be wrong', 'Sometimes confidently so. Check answers against your unit material and test any code yourself.'],
  ['You bring the AI', 'Providers (Anthropic, OpenAI, DeepSeek or another service) need your own account, usually a card or ' +
    'prepaid credit, and often an age of 18+. Usage is billed to you.'],
  ["What's sent", 'Your messages and any files you attach go to the provider you choose, under its privacy terms. ' +
    'EasyUniTrack has no servers and receives nothing.'],
  ["Your uni's rules are yours to follow", "Universities have different rules on AI. The app doesn't check them; it's " +
    'designed to help you learn, not to do your work.'],
  ["It's a beta", 'These features are new, may change, and may not always work as described.'],
];

export const TICKS: Record<string, string> = {
  beta: 'I understand this is a beta feature and may not work as described.',
  rules: "I'm responsible for following my university's rules on using AI, and for checking anything I submit.",
  agree: "I've read and agree to the terms of use.",
};

const TERMS: [string, string][] = [
  ['1. This is a beta',
    'The AI features are new and still being tested. They may not work as described, may change, or may be ' +
    'removed in a later version. Keep backups of anything important (Settings > Your data > Save backup).'],
  ['2. AI can be wrong',
    'Answers, explanations, code and plans come from an AI model and can be inaccurate, incomplete or out of ' +
    'date, sometimes confidently so. Check important information against your unit material, and test any code ' +
    "yourself. Don't rely on the AI features for decisions where a mistake could cause you harm. If a reply is " +
    'wrong, inappropriate or harmful, use Report under it to tell us.'],
  ['3. Your studies are your responsibility',
    "Universities and units have different rules on using AI. It's your responsibility to know and follow the " +
    'rules that apply to you, including academic integrity policies, and to make sure any work you submit is ' +
    "your own and allowed. EasyUniTrack doesn't check or enforce those rules. Tutor modes are designed to help " +
    "you learn, not to guarantee you're following any policy."],
  ['4. Your AI provider',
    'You choose and connect your own provider (such as Anthropic, OpenAI, DeepSeek or a custom service). You ' +
    "need to meet that provider's requirements, including any age and account requirements, and follow its " +
    'terms. Any costs from using your provider are yours. We recommend setting a spending limit with your ' +
    "provider. Your API key is stored in your phone's secure storage, encrypted by the phone; keep your account, " +
    'key and phone secure.'],
  ['5. What gets sent',
    'Your messages and any files you attach are sent to the provider you choose and handled under its privacy ' +
    "terms. EasyUniTrack has no servers and doesn't receive any of it. Only attach material you're allowed to share."],
  ['6. No guarantees',
    'To the extent permitted by law, the AI features are provided "as is", without warranties of any kind, ' +
    "including that they'll be accurate, available, error-free or suitable for your purpose."],
  ['7. Limits on liability',
    "To the extent permitted by law, PandaDev Studio isn't liable for any loss or damage arising from your use of " +
    'the AI features, including academic penalties, lost or changed data, or costs charged by your AI provider. ' +
    'Nothing in these terms excludes rights you have under the Australian Consumer Law or other laws that can\'t be excluded.'],
  ['8. Turning it off',
    'You can turn the AI features off at any time in Settings, which withdraws your agreement. "Remove all AI ' +
    'data" deletes your saved keys, chats and AI settings from EasyUniTrack. Your notes stay.'],
  ['9. Changes',
    'If these terms change, EasyUniTrack will ask you to agree again before you can keep using the AI features.'],
  ['10. Contact', 'Questions: https://github.com/Mysteryman4k/lifeplanner/issues'],
];

export function termsDict() {
  return {
    version: TERMS_VERSION,
    about: ABOUT.map(([title, text]) => ({ title, text })),
    ticks: TICKS,
    terms: TERMS.map(([title, text]) => ({ title, text })),
  };
}

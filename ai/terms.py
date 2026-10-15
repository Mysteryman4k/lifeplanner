"""Terms of use for the AI features, and the plain-language "About" screen shown before them.

The student must agree to the current version (with three ticks) before any AI feature works. Changing
TERMS_VERSION makes the app ask again. The agreement is stored only on this PC, never sent anywhere,
and isn't included in backups.

This is a plain-language draft for review, not legal advice: have a lawyer check it before the public
v4.0. Under the Australian Consumer Law some guarantees can't be excluded, hence "to the extent
permitted by law".
"""

TERMS_VERSION = "1.0"

ABOUT = [
    ("It can be wrong", "Sometimes confidently so. Check answers against your unit material and test any code yourself."),
    ("You bring the AI", "Cloud providers (Anthropic, OpenAI, DeepSeek) need your own account, usually a card or "
                         "prepaid credit, and often an age of 18+. Usage is billed to you. Local models in Ollama "
                         "are free and private, but need a capable PC."),
    ("What's sent", "With a cloud provider, your messages, attached files and any code you share go to that "
                    "provider, under its privacy terms. With a local model in Ollama, nothing leaves your PC "
                    "(Ollama's cloud models are a cloud service). EasyUniTrack has no servers and receives nothing."),
    ("Your uni's rules are yours to follow", "Universities have different rules on AI. The app doesn't check "
                                             "them; it's designed to help you learn, not to do your work."),
    ("Running code", "The Code workspace only runs programs when you click Run, the same as running them in a "
                     "terminal. Only run code you trust."),
    ("It's a beta", "These features are new, may change, and may not always work as described."),
]

TICKS = {
    "beta": "I understand this is a beta feature and may not work as described.",
    "rules": "I'm responsible for following my university's rules on using AI, and for checking anything I submit.",
    "agree": "I've read and agree to the terms of use.",
}

TERMS = [
    ("1. This is a beta",
     "The AI features are new and still being tested. They may not work as described, may change, or may be "
     "removed in a later version. Keep backups of anything important (Settings > Your data > Download backup)."),
    ("2. AI can be wrong",
     "Answers, explanations, code, fixes and plans come from an AI model and can be inaccurate, incomplete or out "
     "of date, sometimes confidently so. Check important information against your unit material, and test any "
     "code yourself. Don't rely on the AI features for decisions where a mistake could cause you harm. If a reply "
     "is wrong, inappropriate or harmful, use Report under it to tell us."),
    ("3. Your studies are your responsibility",
     "Universities and units have different rules on using AI. It's your responsibility to know and follow the "
     "rules that apply to you, including academic integrity policies, and to make sure any work you submit is "
     "your own and allowed. EasyUniTrack doesn't check or enforce those rules. \"Hints first\" and tutor modes "
     "are designed to help you learn, not to guarantee you're following any policy."),
    ("4. Your AI provider",
     "You choose and connect your own provider (such as Anthropic, OpenAI, DeepSeek, a custom service, or Ollama "
     "on your computer). You need to meet that provider's requirements, including any age and account "
     "requirements, and follow its terms. Any costs from using your provider are yours. We recommend setting a "
     "spending limit with your provider. Your API key is stored in Windows Credential Manager on your PC; keep "
     "your account and key secure."),
    ("5. What gets sent",
     "When you use a cloud provider, your messages, any files you attach and any code you share are sent to that "
     "provider and handled under its privacy terms. EasyUniTrack has no servers and doesn't receive any of it. "
     "With a local model in Ollama, everything stays on your PC; Ollama's cloud models are a cloud service and "
     "send your messages to Ollama. Only attach material you're allowed to share."),
    ("6. Running code and changing files",
     "The Code workspace can run commands and programs on your computer and change files in folders you link, but "
     "only when you click Run or Apply. Running code can affect your computer and files, and programs you run "
     "can access anything your Windows account can, including your saved API key. Only run code you trust. "
     "Backups are kept for changes you apply, but you're responsible for your own files and projects."),
    ("7. No guarantees",
     "To the extent permitted by law, the AI features are provided \"as is\", without warranties of any kind, "
     "including that they'll be accurate, available, error-free or suitable for your purpose."),
    ("8. Limits on liability",
     "To the extent permitted by law, PandaDev Studio isn't liable for any loss or damage arising from your use of "
     "the AI features, including academic penalties, lost or changed files or data, costs charged by your AI "
     "provider, or problems caused by code you run. Nothing in these terms excludes rights you have under the "
     "Australian Consumer Law or other laws that can't be excluded."),
    ("9. Turning it off",
     "You can turn the AI features off at any time in Settings, which withdraws your agreement. \"Remove all AI "
     "data\" deletes your saved keys, chats, linked folder records (not the folders), suggested code changes and "
     "their backups, and your AI settings from EasyUniTrack. Your notes stay."),
    ("10. Changes",
     "If these terms change, EasyUniTrack will ask you to agree again before you can keep using the AI features."),
    ("11. Contact", "Questions: https://github.com/Mysteryman4k/lifeplanner/issues"),
]


def as_dict() -> dict:
    return {"version": TERMS_VERSION, "about": [{"title": t, "text": x} for t, x in ABOUT],
            "ticks": TICKS, "terms": [{"title": t, "text": x} for t, x in TERMS]}

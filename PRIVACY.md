# EasyUniTrack privacy policy

_Last updated: 15 October 2026_

EasyUniTrack is a planner for students made by PandaDev Studio. It's built so that your information stays with you.

## The short version

EasyUniTrack doesn't collect, sell or share your information. PandaDev Studio has no servers and receives nothing from the app. There are no accounts, no sign-in, no advertising and no analytics or tracking.

Your planner stays on your computer. The only exceptions are the update check in the GitHub version, explained under [Internet use](#internet-use), and the optional AI features.

The AI features (the study assistant and the code workspace) are off until you turn them on. When you use them with a cloud AI provider you've chosen, the messages and material you send go to that provider, as explained under [The AI features](#the-ai-features-optional). With a local model in Ollama, they stay on your computer.

## What the app stores, and where

Everything is saved in a file on your own computer:

- Microsoft Store version: in the app's own data folder that Windows manages for you. If you used the GitHub version on the same computer before, the Store version keeps using that existing `%APPDATA%\EasyUniTrack` folder instead
- Version from GitHub: `%APPDATA%\EasyUniTrack`

That file holds:

- **Your planner:** tasks, subjects, calendar items, notes, job applications, money records and settings.
- **If you use the AI features, also:**
  - your saved chats, including the text of the pages you chose from any attached file;
  - summaries of long chats;
  - the code folders you linked (where they are, not their files);
  - code changes the assistant suggested, and a record of the changes it made to your tasks, so you can undo them;
  - your AI settings. These include which provider and model you chose, and when you agreed to the AI terms.

When you click Apply on a suggested code change, a copy of the original file is kept in a `code-backups` folder next to the data file, so Undo can put it back.

The app also keeps an automatic daily backup copy of the data file in the same folder. **Download backup** saves your planner, notes, saved chats and linked folder records to a file you choose. It doesn't include your AI settings or terms agreement.

None of this ever leaves your computer unless you choose to move it, for example by copying a backup file somewhere yourself. Only people who can sign in to your Windows account can open these files, the same as your other documents.

## The AI features (optional)

The AI features are off by default. Nothing about them is sent anywhere until you agree to their [terms of use](TERMS.md), choose a provider and use them.

**Your AI provider.** You choose where the AI runs:

- **Cloud providers:** Anthropic, OpenAI, DeepSeek, or another OpenAI-compatible service whose address you enter.
- **Local models with Ollama on your computer:** nothing leaves your computer. Ollama's "cloud" models are the exception: they run on Ollama's servers, and EasyUniTrack labels them.

Your account with a cloud provider, and what the provider does with what you send, are covered by that provider's own terms and privacy policy.

**What's sent to your provider, and when.** Only when you ask something, or use an action like Explain the error, Quiz me or Videos, EasyUniTrack sends that request to your provider. It includes:

- your message, and recent messages from the same chat. In long chats, older messages are summarised by your provider and the summary is sent instead;
- the details of a task when you use **Help me with this** (its title, subject, type, due date, priority, hours, description and notes);
- your task list (titles, due dates, priorities, status and subjects) when the assistant looks it up to answer you or to change tasks you asked about;
- the text of the pages or slides you chose from a file you attach. The file itself stays on your computer: EasyUniTrack reads the text out of it there;
- in the code workspace, the files listed under your question. You can take any off before sending. Also any error or program output you paste or choose to include, and for **Explain my change**, what changed in the file.

The app shows how many tokens each chat has used. **Test connection** uses your key only to ask the provider which models you can use.

**Your API key** is stored in Windows Credential Manager on your computer. It's never written to EasyUniTrack's data file, backups or logs, and it's only sent to the provider it belongs to. Programs running under your Windows account can read Credential Manager, so only run code you trust (see the terms).

**Running code.** The code workspace can run programs you choose, on your computer, with your permissions, only when you click Run. Their output is shown in the app and isn't saved or sent anywhere unless you include it in a question.

**Reporting a reply.** **Report** under a reply opens a new GitHub issue in your web browser, with the reply's text filled in. You can edit or remove anything before you choose to submit it, and nothing is sent unless you do.

## Internet use

- **Microsoft Store version:** the app connects to the internet only if you use the AI features with a cloud provider. The Microsoft Store handles updates.
- **Version from GitHub:** to tell you about new versions, the app asks GitHub for the latest release each time you open it, and when you press **Check now**. This request contains no information about you or your data. You can turn this off in **Settings → Updates**. It also connects to your AI provider, as above, if you use the AI features with a cloud provider.
- Like any website, GitHub and AI providers can see your computer's IP address when they're contacted; see [GitHub's privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement) and your provider's policy.
- Links you click, such as a job advertisement link you saved or a YouTube search the assistant suggests, open in your own web browser.

## Notifications and Start with Windows

Reminder notifications are created on your computer from your own tasks. "Start with Windows" only opens the app when you sign in. Both can be turned off in **Settings**.

## Removing your information

- You can delete any item or chat in the app at any time.
- **Keep chats** in Settings can delete chats you haven't continued for a month to a year. Suggested code changes, their backups and the record of task changes are cleared automatically after 90 days.
- **Remove all AI data** in Settings deletes your saved API keys, chats, linked folder records, suggested code changes and their backups, and AI settings. Your notes and linked folders themselves aren't touched.
- To remove information you've already sent to a cloud AI provider, use that provider's own controls.
- Uninstalling the Microsoft Store version removes the data it created. If you used the GitHub version on the same computer before, the existing `%APPDATA%\EasyUniTrack` folder is kept after uninstalling; delete it yourself to remove that data too.
- For the GitHub version, delete the `%APPDATA%\EasyUniTrack` folder to remove everything.
- Before uninstalling, use **Settings → Your data → Download backup** if you want to keep a copy.

## Children

EasyUniTrack doesn't collect information from anyone, including children. AI providers set their own age requirements, often 18 or older, which you need to meet to use them.

## Changes to this policy

If this policy changes, the new version will be posted here with a new date.

## Contact

Questions about privacy: open an issue at <https://github.com/Mysteryman4k/lifeplanner/issues>.

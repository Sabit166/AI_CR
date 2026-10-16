<div align="center">

# 🎓 AI CR

### Your class representative's assistant on Discord — exam dates, syllabus and notes, one command away

*Type a slash command in your class channel. Get the answer straight from what your CR posted.*

</div>

---

## 📖 Contents

- [What is AI CR?](#-what-is-ai-cr)
- [For students](#-for-students)
- [For class representatives](#-for-class-representatives)
- [Setting up a new class](#-setting-up-a-new-class)
- [How the week works](#-how-the-week-works)
- [Frequently asked questions](#-frequently-asked-questions)

---

## 🏛️ What is AI CR?

Every term, the same questions fill the class group:
*"When is the next CT?"* · *"What's the syllabus?"* · *"Which exams are next week?"*

**AI CR** is a Discord bot that answers them. **Each class has its own channel**, and in that channel the bot only
knows that class's courses and exams. Your CR posts each exam once; the bot answers everyone, any time, with exactly
what was posted — and announces next week's exams and tomorrow's exams on its own.

| | |
|---|---|
| 💬 **Students** | Use the slash commands in your class channel, or open your class's exam list with `/exams`. |
| 🗂️ **Class representatives** | `/manage` opens the editor for your class — no account, no password. |

---

## 🎒 For students

### Slash commands

Type `/` in your class channel and pick a command. The answer is shown **only to you**, so the channel stays tidy.

| Command | What you get |
|---|---|
| `/this-week` | This week's remaining exams (today until Thursday) |
| `/next-week` | Next week's exams, Sunday to Thursday |
| `/next-exam-day` | **Every** exam on the next day that has one — times, sections, syllabus, venue, teachers |
| `/next-exam-notes` | The notes links for the exams on the next exam day |
| `/exams` | A button that opens your class's list of upcoming exams |
| `/ask` | Ask in your own words, e.g. *"When is the next CT of CSE-415?"* |

### Updates in the channel

You don't even have to ask:

- **Every Friday at 6 PM** the bot posts **next week's exams**.
- **At 8 PM the evening before an exam day** it posts all of that day's exams, with the time of each one.
- Your CR can also post an update at any time — for a week, or for a single exam.

### The exam list

`/exams` gives you a link to your class's exam list: every upcoming exam grouped into **This week**, **Next week** and
**Later**, with syllabus, times and notes, a course filter and a **Past** tab. It's read-only, needs no account and
shows only your class.

> 📱 **Tip:** open it once and use your browser's **Add to Home Screen** — it then opens like an app.

### Asking with `/ask`

| You want to know… | Try asking |
|---|---|
| 📖 A syllabus | *"Syllabus of the next Database CT"* · *"What's in HCI CT 2?"* |
| ☀️ A particular day | *"Anything tomorrow?"* · *"Exams on Monday"* · *"What's on 27 October?"* |
| 👩‍🏫 A teacher's exams | *"Next exam of Nafisa madam"* |
| 🧑‍🤝‍🧑 Your section | *"Next week's exams for section A"* |
| 📚 A whole course | *"All upcoming exams of CSE-464"* |

You don't need the exact course title. A **course code** (`CSE-415`, `cse 415`), the **full title**
(*Human Computer Interface*), a **short name** (*HCI*, *DBMS*) or **a subject word** (*"the database exam"*) all work.
If your words could mean more than one course, the bot asks which one — ask again with the course code.

Everything the bot says comes from what your CR posted. If something hasn't been posted yet, it says so plainly — it
never makes up a date or a syllabus.

> 💡 **Tip:** If a date or syllabus looks wrong, tell your CR — once they fix it, every answer updates immediately.

---

## 🧑‍💼 For class representatives

### Who counts as a CR

In a class channel, you're a CR if you have the **Manage Channels** permission there, or the **CR role** chosen when
the class was set up. Nobody else can open the editor.

### Opening the editor

1. In your class channel, type **`/manage`**.
2. The bot replies with an **Open CR editor** button that **only you can see**.
3. Tap it — the editor opens straight into your class. No sign-in.

The link works for **12 hours**; after that, run `/manage` again. **Don't share it**: anyone with the link can edit
your class's exams until it expires.

The editor has three tabs at the bottom of the screen:

| Tab | What it's for |
|---|---|
| 🗓 **Exams** | Post, edit and delete exams, and post updates to Discord |
| 📘 **Courses** | This term's courses and who teaches them |
| 👤 **Faculty** | The list of teachers |

### ✅ Start of term — a one-time setup

1. **Faculty** → add each teacher's full name.
2. **Courses** → **+ Add course** for every course this term:
   - Type the **course code** (e.g. `CSE-415`). Whether it's Theoretical or Sessional is filled in for you.
   - Enter the **course title**.
   - Add any **short names** students use (e.g. *HCI*, *DBMS*) so `/ask` recognises them.
   - Choose the **course teachers**. A Theoretical course has two course sections, **A** and **B**: pick the
     teacher for each. The same teacher can take both sections. For a Sessional course, tick as many teachers as
     take it.
3. Remove last term's courses with **Remove**. Their old exam records are kept.

### ✍️ Posting an exam

1. Go to **Exams** → **+ New exam**.
2. Tap the **course**. The title appears automatically.
3. Choose the **exam type**. Only the right options appear:

   | Theoretical courses | Sessional courses |
   |---|---|
   | CT 1 · CT 2 · Mid · CT 3 | Project Update · Evaluation · Online Exam · Project Presentation · Lab Test |

4. **Theoretical:** choose the **section**: **Section A**, **Section B**, or **Both sections**. The
   section's teacher is filled in for you. Post each section separately when the syllabus differs, or once with
   **Both sections** when it's the same.
   **Sessional:** enter the class **section**, or leave it empty if it's for the whole class, and optionally
   tick the **teacher(s)** taking it.
5. Choose the **date** from the list, and the **time** (hour and minutes) if you know it.
   For a Theoretical exam, both sections sit it at the same time. If the other section's exam is already
   posted, its date and time are filled in for you, and saving a new date or time moves both.
6. Write the **syllabus**. Line breaks are kept exactly as you type them.
7. Optionally open **More details** for venue, a notes link, or remarks.
8. Tap **Preview** to check it, then **Save exam**.

Students see it in the bot's answers and on the exam list the moment you save. To announce it in the channel, tap
**📣 Post** on the exam.

### 📣 Posting to the class channel

At the top of **Exams** there are four buttons. Each asks you to confirm, then posts in the class channel for everyone:

| Button | Posts |
|---|---|
| **This week** | This week's remaining exams |
| **Next week** | Next week's exams |
| **Next exam day** | Every exam on the next exam day, with times |
| **Next exam notes** | The notes links for the next exam day |

Each upcoming exam also has a **📣 Post** button that announces just that exam (useful after a change).

**Automatic updates** (the switch under the buttons) post next week's exams every Friday at 6 PM and a reminder at
8 PM the evening before each exam day. They're on by default; you can turn them off for your class there.

### 🔁 Making changes

- **Edit anything at any time.** Tap **Edit** on an exam or course, change it, and save. The bot and the exam list update immediately.
- **Delete an exam** with **Delete** (you'll be asked to confirm).
- **Past exams** are under **Exams → Past**.
- **Removing a course** that already has exams only takes it off this term's list — its exam history is kept.

### 🛟 Good to know

- **Nothing is lost if a save fails.** Your entries stay in the form; just tap Save again.
- **Closed the page by accident?** Your unfinished exam is restored the next time you tap **+ New exam**.
- **Tapped Save twice?** Only one exam is created. Tapping a Post button twice posts once.
- **Duplicates aren't allowed** — edit the existing exam instead. A Theoretical course has one CT 1 (CT 2, Mid…) per section; a Sessional course can't have two exams of the same type on the same day for the same section.

---

## 🧭 Setting up a new class

Anyone with **Manage Channels** in the class's channel (usually the server admin or a CR):

1. Make sure the bot is in your server and can **view** the channel and **send messages** in it.
2. In the channel, run **`/setup name:<class name>`** — for example `/setup name:CSE 22 Section A`.
   - Add **`cr_role:`** to choose a role whose members count as CRs.
   - Add **`auto_updates:False`** if you don't want the automatic Friday and evening posts.
3. That's it: the channel is now the class. A CR runs `/manage` and adds the term's faculty and courses.

Run `/setup` again in the same channel to rename the class or change the CR role. Every channel you set up is a
separate class with its own courses, exams and exam list.

---

## 📆 How the week works

Our academic week runs **Sunday to Thursday**, and all dates follow **Bangladesh time**.

| When you ask… | You get… |
|---|---|
| `/this-week` | From **today** until **Thursday** |
| `/this-week` on **Friday or Saturday** | The week is over, so you're shown **next week** instead |
| `/next-week` | The **coming Sunday to Thursday** |
| `/next-exam-day` | The nearest day with an exam, and **all** the exams on it (today counts until its exams have started) |
| *"Tomorrow"*, *"Monday"*, *"27 October"* with `/ask` | That exact day |

---

## ❓ Frequently asked questions

<details>
<summary><b>The bot says no exam has been posted. Does that mean there's no exam?</b></summary>

It means your CR hasn't posted one for that time yet. When in doubt, check with your CR or teacher.
</details>

<details>
<summary><b>The bot says this channel isn't linked to a class.</b></summary>

Commands only work in a channel that was set up with <code>/setup</code>. Use your class's channel, or ask someone with Manage Channels to set it up.
</details>

<details>
<summary><b>Do I need an account to see the exam list?</b></summary>

No. Run <code>/exams</code> in your class channel and open the link.
</details>

<details>
<summary><b>It says it couldn't reach the database.</b></summary>

That's a temporary connection problem, not "no exams". Try again in a minute.
</details>

<details>
<summary><b>Can students change exam information?</b></summary>

No. Only CRs can open the editor, and an editor link only works for the class it was made for.
</details>

<details>
<summary><b>My editor link stopped working.</b></summary>

Editor links last 12 hours. Run <code>/manage</code> again for a new one.
</details>

<details>
<summary><b>How do sections work for CTs and the Mid?</b></summary>

Theoretical courses have two course sections, A and B, each with its own course teacher (sometimes the same teacher takes both). CTs and the Mid happen at the same time for both sections, but each section's teacher may set a different syllabus, so a CT can be posted for Section A, Section B, or both. Ask for *"section A"* and you'll see your section's exams plus anything posted for both. Sessional exams can be at different times for different class sections.
</details>

---

<div align="center">

**Made for our class, by our class.** 📚

*For maintainers: setup, deployment and technical details are in the [Developer Guide](docs/DEVELOPER.md).*

</div>

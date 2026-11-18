Read the task and relevant existing files. Preserve shared constraints and earlier behavior.
The workspace already contains tested generic code described under "Workspace building blocks" (errors, validation, passwords, sessions, API client, router, form controls). Use it instead of writing your own; replace a block only when a requirement needs behavior it cannot provide.
For substantial work, keep a short plan that you revise when observations warrant it.
Choose the order of work from the actual dependencies. You may work across application layers in one task.
Use the provided tools and retain their observations; avoid repeating unchanged reads.
Every model request resends the whole conversation, so do as much as possible per response:
- issue all independent tool calls of a step together in one response instead of one call per response;
- read every file you need at once with read_files, and create or rewrite independent files at once with write_files;
- group exact edits across files in one apply_patch;
- use verify_application (kind all) to install, typecheck, build and test in one call, and process_start with
  probe_path to start a service and observe its first response in one call.
Calls of one response run in the order given; only keep a call for a later response when it depends on a result
you have not seen yet.
Prefer precise edits. Diagnose errors from evidence and correct their cause.
Rules the external acceptance tests rely on:
- Give every element listed under "interface_contract" exactly that role and accessible name.
- Links and buttons: a control is a link (<a href>) only when the requirements call it a link (a "Register link",
  role=link) or it is an entry of a navigation menu. Every other control the requirements name ("Edit", "New Page",
  "Create New Book", "Cancel", "Save"...) is a <button>, also when it opens another page: navigate in its onClick.
  Tests locate those unannotated controls as buttons.
- Use plain native HTML: one element per action. Never nest interactive
  elements (a button or role="button" inside a link), never add a role attribute or a duplicate element to satisfy
  a test. A test that demands a structure the requirement does not state is wrong: dispute it (see below).
- An element of the interface_contract is unique on each page: never show a second control with the same role and
  name elsewhere on the page (for example a second "Sign in" button in the page body besides the one in the
  header; give the extra one another name such as "Sign in to continue"). Tests locate it by role and name alone
  and fail when two match.
- A choice among fixed options (a type, a class, a category) is a native <select> whose label is the field's name;
  tests call selectOption on it. Any control a test clicks by its visible name appears once on the page: a
  calendar showing two months must not offer two buttons with the same date name (hide or rename the duplicate).
- A visual item a requirement names (an avatar, a logo, an icon, a picture) is an image: an <img> with an alt text,
  or an element with role="img" and an aria-label (initials inside it are fine), never letters alone.
- What a requirement describes as part of a region (its author block, its comments, its controls) is nested inside
  that region's element: tests look for it inside the region. A region a requirement places on several pages
  (for example the list shown on the home page and on the list page) exists on each of them.
- A value the requirements name (a date, a count, a score, badges) also shows a visible text label before it, worded
  as in the original product: "Created 2026-07-01", "Viewed 42 times", "3 reviews". Tests read that text as well as
  the role=status element.
- Each piece of information a requirement names (an author, a date, a count, a status) is its own element, for
  example <span>Ada Lovelace</span> · <time>…</time>, never glued to other text: tests match it as exact text.
- Use the exact texts the requirements give for labels, buttons, links, headings and placeholders. A field
  described by an inline hint (for example "Write your page content here...") gets that text both as its
  accessible name and as its placeholder. When a requirement says fields are "also exposed with those
  placeholders" (or names a placeholder), every one of those fields gets its exact name as placeholder too.
- Never paginate, truncate or limit a list unless a requirement asks for it: the tests run in parallel on one
  shared database, so lists hold many records created by other tests, and each must still appear exactly once.
- A navigation a requirement states (for example "Save returns to the parent") always happens, whatever page
  the user came from. Never make behavior depend on how a page was reached.
- When a test failure seems to contradict a requirement, follow the requirement; never add special cases to
  satisfy one test. Each failure says what the page showed: if your application rightly rejected what the test
  entered (a validation message), or the test demands what no requirement states, call run_acceptance_tests with
  disputes (the scenario and the requirement text it contradicts). The host has that test reviewed.
- Record each cause you establish with note_write: notes survive compaction, the conversation does not.
Write in parallel whenever the application has independent parts. First write the shared contract yourself: database tables and startup data, API routes with their request and response shapes, shared types, and the page list with their routes. Then call delegate_tasks once with 2 to 4 cohesive tasks (for example the backend routes, and one task per group of related pages), each owning its own files or directories. Keep tightly coupled files in the same task. After they return, connect the parts (route registration, navigation), then verify. Skip delegation for a very small application.
Time is limited. Write the whole application first, then run verify_application (kind all) and fix what it reports. Then call run_acceptance_tests instead of testing journeys by hand with curl, database queries or the browser: it runs every acceptance test on a fresh database and lists each failure with its requirement. Fix those, run it again, and reply with your completion summary when it passes. Work only inside the workspace: host files outside it (session state, test tooling) are not part of your task.
Verify changes using the capabilities actually available. If execution or browser tools are absent,
state that runtime behavior remains unverified; do not invent test results.
Finish with the changes, observations and remaining limitations. A final reply proposes completion;
the host and external evaluator determine application acceptance.

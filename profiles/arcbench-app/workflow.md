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
- Use the exact texts the requirements give for labels, buttons, links, headings and placeholders. A field
  described by an inline hint (for example "Write your page content here...") gets that text both as its
  accessible name and as its placeholder.
- Never paginate, truncate or limit a list unless a requirement asks for it: the tests run in parallel on one
  shared database, so lists hold many records created by other tests, and each must still appear exactly once.
- A navigation a requirement states (for example "Save returns to the parent") always happens, whatever page
  the user came from. Never make behavior depend on how a page was reached.
- When a test failure seems to contradict a requirement, follow the requirement and say so in your reply;
  never add special cases to satisfy one test.
Write in parallel whenever the application has independent parts. First write the shared contract yourself: database tables and startup data, API routes with their request and response shapes, shared types, and the page list with their routes. Then call delegate_tasks once with 2 to 4 cohesive tasks (for example the backend routes, and one task per group of related pages), each owning its own files or directories. Keep tightly coupled files in the same task. After they return, connect the parts (route registration, navigation), then verify. Skip delegation for a very small application.
Time is limited. Write the whole application first, then run verify_application (kind all) and fix what it reports. Then call run_acceptance_tests instead of testing journeys by hand with curl, database queries or the browser: it runs every acceptance test on a fresh database and lists each failure with its requirement. Fix those, run it again, and reply with your completion summary when it passes. Work only inside the workspace: host files outside it (session state, test tooling) are not part of your task.
Verify changes using the capabilities actually available. If execution or browser tools are absent,
state that runtime behavior remains unverified; do not invent test results.
Finish with the changes, observations and remaining limitations. A final reply proposes completion;
the host and external evaluator determine application acceptance.

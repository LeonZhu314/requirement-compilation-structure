Checking the application the way independent acceptance tests do:
- Verify the built application, not only the dev server: `verify_application build`, then
  `process_start` with `npm run start` and PORT, then the browser on that port.
- Use the browser tool with `role` and `name` exactly as the requirement words them. If the element is not
  found by role and exact name, an acceptance test will not find it either.
- Walk each scenario as written: Given state, When action, Then visible outcome; then reload the page when
  the scenario mentions refresh or persistence, and check the outcome again.
- Check rejections too: the error is visible, and after reloading nothing was created or signed in.
- Use two different accounts when a scenario is about identity or ownership.
- Read `browser logs` after a failure: a 4xx/5xx response or a page error usually names the cause.
- Declare the pages you serve with interface_write, including the reference image id of each page.

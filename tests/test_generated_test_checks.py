"""Static checks on the host's generated tests, before they cost a verification round."""

import unittest

from infrastructure.verification.acceptance import REVIEWER, unopened


def spec(*bodies, preamble=''):
    return "import { test, expect } from '@playwright/test';\n" + preamble + ''.join(
        f"test('SCN-{index}: case', async ({{ page }}) => {{\n{body}\n}});\n" for index, body in enumerate(bodies))


class OpenedApplicationTests(unittest.TestCase):
    def test_a_test_that_never_navigates_is_rejected_with_its_title(self):
        problem = unopened(spec("  await page.goto('/');", "  await page.getByRole('link', { name: 'Books' }).click();"))
        self.assertIn("'SCN-1: case' never navigates", problem)

    def test_navigation_through_a_helper_or_a_hook_counts(self):
        helper = "async function openBooks(page) {\n  await page.goto('/books');\n}\n"
        self.assertIsNone(unopened(spec('  await openBooks(page);', '  await openBooks(page);', preamble=helper)))
        hook = "test.beforeEach(async ({ page }) => { await page.goto('/'); });\n"
        self.assertIsNone(unopened(spec("  await page.click('a');", preamble=hook)))
        # A helper that does not navigate does not count.
        other = "const fill = async (page) => { await page.fill('x', 'y'); };\n"
        self.assertIsNotNone(unopened(spec('  await fill(page);', preamble=other)))

    def test_the_reviewer_knows_this_defect(self):
        self.assertIn('never opens the application', REVIEWER)


if __name__ == '__main__':
    unittest.main()

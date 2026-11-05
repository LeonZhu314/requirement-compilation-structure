import { test, expect, type Page } from "@playwright/test";

const STRONG_PASSWORD = "Str0ng!Passw0rd12";

function textboxByLabel(page: Page, label: string) {
  return page.getByRole("textbox", { name: new RegExp(`^\\s*\\*?\\s*${label}\\s*:?\\s*$`) });
}

function optionsWithLabel(page: Page, label: string) {
  return page.getByLabel(new RegExp(`^\\s*\\*?\\s*${label}\\s*:?\\s*$`));
}

function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 10000)}`;
}

async function fillValidRegistration(page: Page, username: string) {
  await page
    .getByRole("combobox", { name: /^\s*\*?\s*Nationality\s*:?\s*$/ })
    .selectOption({ label: "Vietnam" });
  await textboxByLabel(page, "Name").fill("Playwright Traveler");
  await textboxByLabel(page, "Passport number").fill("AB123456");
  await textboxByLabel(page, "Passport expiration date").fill("2035-12-31");
  await textboxByLabel(page, "Date of birth").fill("1990-05-05");
  await page.getByRole("radio", { name: "Male", exact: true }).check();
  await textboxByLabel(page, "Username").fill(username);
  await optionsWithLabel(page, "Password").fill(STRONG_PASSWORD);
  await optionsWithLabel(page, "Confirm Password").fill(STRONG_PASSWORD);
  await textboxByLabel(page, "Email address").fill(`${username}@example.com`);
}

test.describe("REQ-2 traveler registration", () => {
  test("registers a traveler from the header Register link and returns signed in to the home page", async ({ page }) => {
    const username = `e2e_${uniqueSuffix()}`;

    await page.goto("/");
    await page.getByRole("link", { name: "Register", exact: true }).click();
    await expect(page).toHaveURL(/\/register$/);

    await expect(page.getByText(/Current location:/)).toBeVisible();
    const homeCrumb = page.getByRole("link", { name: "HOME", exact: true });
    await expect(homeCrumb).toBeVisible();
    await expect(homeCrumb).toHaveAttribute("href", "/");
    await expect(page.getByText("Create an account", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Create an account", exact: true })).toHaveCount(0);

    await expect(page.getByRole("combobox", { name: /^\s*\*?\s*Nationality\s*:?\s*$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: "Check the rules for filling out passport information", exact: true })).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: /^\s*\*?\s*Gender\s*:?\s*$/ })).toBeVisible();
    await expect(page.getByRole("radio", { name: "Male", exact: true })).toBeVisible();
    await expect(page.getByRole("radio", { name: "Female", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Terms of Service", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Privacy Policy", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Cookie Statement", exact: true })).toBeVisible();

    await fillValidRegistration(page, username);

    await page
      .getByRole("checkbox", {
        name: "I have read and agree to abide by Terms of Service and Privacy Policy of 12306.cn.",
        exact: true,
      })
      .check();

    await page.getByRole("button", { name: "Next step", exact: true }).click();

    await page.waitForURL(/\/$/);
    await expect(page.getByText(username, { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign out", exact: true })).toBeVisible();

    await page.reload();
    await expect(page.getByText(username, { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign out", exact: true })).toBeVisible();
  });

  test("shows an error and creates no session when the agreement is not checked", async ({ page }) => {
    const username = `e2e_${uniqueSuffix()}`;

    await page.goto("/register");
    await fillValidRegistration(page, username);
    await page.getByRole("button", { name: "Next step", exact: true }).click();

    const errorArea = page.locator('[data-ui-id="UI_000109"]').or(page.getByRole("alert"));
    await expect(errorArea.first()).toBeVisible();
    await expect(errorArea.first()).not.toHaveText("");
    await expect(page).toHaveURL(/\/register$/);

    const session = await page.request.get("/api/session");
    expect(session.ok()).toBeTruthy();
    const body = (await session.json()) as { authenticated: boolean; username: string | null };
    expect(body).toEqual({ authenticated: false, username: null });

    await page.goto("/");
    await expect(page.getByRole("link", { name: "Register", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign out", exact: true })).toHaveCount(0);
  });
});

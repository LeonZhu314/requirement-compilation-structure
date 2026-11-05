import { test, expect } from "@playwright/test";

test.describe("REQ-1 public home page account access", () => {
  test("guest header shows Register and Login links to the account pages", async ({ page }) => {
    await page.goto("/");
    const register = page.getByRole("link", { name: "Register", exact: true });
    const login = page.getByRole("link", { name: "Login", exact: true });

    await expect(register).toBeVisible();
    await expect(login).toBeVisible();
    await expect(register).toHaveAttribute("href", "/register");
    await expect(login).toHaveAttribute("href", "/login");
  });

  test("home page exposes the specified search and banner controls", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("textbox", { name: "From", exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "To", exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Date", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Search", exact: true })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "High-speed trains only", exact: true })).toBeVisible();

    await expect(page.getByRole("button", { name: "Swap stations", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Show banner 1", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Show banner 2", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Show banner 3", exact: true })).toBeVisible();
  });

  test("quick guide and footer entries use the specified accessible names", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("link", { name: "What ID documents are accepted by 12306.cn English website?", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "What services does 12306.cn English website provide?", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "What is endorsement?", exact: true })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "What are the rules of ticket endorsement?", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "More>", exact: true })).toBeVisible();

    await expect(page.getByRole("link", { name: "Privacy Policy", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Cookie Statement", exact: true })).toBeVisible();
  });

  test("shared navigation entries use the specified roles", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("link", { name: "Home", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Booking", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Travel guides", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "My 12306", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "简体中文", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Contact us", exact: true })).toBeVisible();
  });
});

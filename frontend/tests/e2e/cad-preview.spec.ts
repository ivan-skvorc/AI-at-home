import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  amplifyingGlb,
  cadFixtures,
  mockCadPreview,
  pngPixel,
  pngRow,
} from "./utils/cad-preview";
import { mockLangGraphAPI } from "./utils/mock-api";

// No GPU in CI: WebGL runs on SwiftShader, which Chromium only offers with
// this flag. A local Chromium of another revision comes from the environment.
test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"],
  },
});

const threadId = "00000000-0000-0000-0000-000000004646";
const models = [
  "mounting-plate.glb",
  "mounting-plate.stl",
  "mounting-plate-1.failed.glb",
  "split-plate.glb",
];
const outputs = [...models, "huge.glb", "amplifying.glb"].map(
  (name) => `/mnt/user-data/outputs/${name}`,
);
const huge = Buffer.alloc(26 * 1024 * 1024);
const amplifying = amplifyingGlb();
const readerURL = (name: string) =>
  `/artifacts/view?path=${encodeURIComponent(`/mnt/user-data/outputs/${name}`)}&thread_id=${threadId}`;

type Probe = {
  created: number;
  live: number;
  frames: number;
};

async function setup(
  page: Page,
  width: number,
  plugins: "enabled" | "disabled" | "none" = "enabled",
) {
  await page.setViewportSize({ width, height: width < 600 ? 844 : 960 });
  await page.addInitScript(() => {
    localStorage.setItem("theme", "light");
    // Count live WebGL contexts and the viewer's own animation frames.
    const probe = { created: 0, live: 0, frames: 0 };
    Object.assign(window, { cadProbe: probe });
    const getContext = Reflect.get(
      HTMLCanvasElement.prototype,
      "getContext",
    ) as (this: HTMLCanvasElement, ...args: unknown[]) => unknown;
    Reflect.set(
      HTMLCanvasElement.prototype,
      "getContext",
      function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
        const context = getContext.call(this, type, ...rest);
        const canvas = this as HTMLCanvasElement & { counted?: boolean };
        if (context && type.startsWith("webgl") && !canvas.counted) {
          canvas.counted = true;
          probe.created++;
          probe.live++;
          canvas.addEventListener("webglcontextlost", () => probe.live--, {
            once: true,
          });
        }
        return context;
      },
    );
    const frame = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) => {
      if (new Error().stack?.includes("/api/plugins/cad-preview/"))
        probe.frames++;
      return frame(callback);
    };
  });
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadId,
        title: "Mounting plate",
        artifacts: outputs,
        messages: [
          { type: "human", id: "ask", content: "Make a mounting plate" },
          {
            type: "ai",
            id: "ready",
            content: "The plate is ready.",
            tool_calls: [
              {
                id: "present",
                name: "present_files",
                args: { filepaths: outputs },
              },
            ],
          },
        ],
      },
    ],
  });
  await mockCadPreview(page, { plugins });
  await page
    .context()
    .route(`**/api/threads/${threadId}/artifacts/**`, async (route) => {
      const name = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").pop()!,
      );
      const body =
        name === "huge.glb"
          ? huge
          : name === "amplifying.glb"
            ? amplifying
            : await readFile(path.join(cadFixtures, name));
      await route.fulfill({ body, contentType: "application/octet-stream" });
    });
}

async function openInPanel(page: Page, name: string) {
  await page.goto(`/workspace/chats/${threadId}`);
  await expect(page.getByText("The plate is ready.")).toBeVisible();
  await page
    .getByRole("button", {
      name: `${name} ${name.split(".").pop()!.toUpperCase()}`,
      exact: true,
    })
    .click();
  return panelOf(page);
}

const panelOf = (page: Page) =>
  page.locator("#artifacts, [role=dialog]").first();

async function switchTo(page: Page, name: string) {
  await panelOf(page).getByRole("combobox").click();
  await page.getByRole("option", { name, exact: true }).click();
}

const preview = (scope: Page | Locator, name: string) =>
  scope.locator(`div[aria-label="${name}"]`);

async function expectModel(page: Page, name: string) {
  const host = preview(page, name);
  const canvas = host.locator("canvas");
  await expect(canvas).toBeVisible({ timeout: 20_000 });
  const report = JSON.parse(
    await readFile(
      path.join(
        cadFixtures,
        name.replace(/(\.failed)?\.(glb|stl)$/, ".report.json"),
      ),
      "utf8",
    ),
  ) as { expected: { bodies?: number }; measured: { bbox_mm: number[] } };
  const dims = host.locator(".dims");
  await expect(dims).toHaveText(/^Bounding box .+ mm \(from the mesh\)$/);
  const shown = /([\d.,]+) × ([\d.,]+) × ([\d.,]+)/
    .exec((await dims.textContent())!)!
    .slice(1)
    .map((value) => Number(value.replaceAll(",", "")));
  shown.forEach((value, axis) =>
    expect(
      Math.abs(value - report.measured.bbox_mm[axis]!),
    ).toBeLessThanOrEqual(0.1),
  );
  // One body covers the middle of a fitted view; the corner is background.
  // Bodies laid side by side along X each cross the middle row of the top
  // view, with background between them: one run of drawn pixels per body.
  const bodies = report.expected.bodies ?? 1;
  if (bodies > 1)
    await host.getByRole("button", { name: "Top view", exact: true }).click();
  await expect
    .poll(async () => {
      const png = await canvas.screenshot();
      const box = (await canvas.boundingBox())!;
      const scale = png.readUInt32BE(16) / box.width;
      const corner = pngPixel(png, 3, 3);
      const drawn = pngRow(png, Math.floor((box.height / 2) * scale)).map(
        (pixel) => pixel.some((value, i) => Math.abs(value - corner[i]!) > 12),
      );
      // Read three pixels in from each side, like the corner: a screenshot at
      // a fractional offset can catch the panel's border in its edge column.
      const inner = drawn.slice(3, -3);
      return {
        centre: drawn[Math.floor((box.width / 2) * scale)],
        runs: inner.filter((on, x) => on && !inner[x - 1]).length,
      };
    })
    .toMatchObject(bodies === 1 ? { centre: true } : { runs: bodies });
  await expect(host.locator(".banner")).toHaveCount(
    name.endsWith(".failed.glb") ? 1 : 0,
  );
  if (name.endsWith(".failed.glb"))
    await expect(host.locator(".banner")).toContainText(
      "mounting-plate-1.report.json",
    );
  if (process.env.DEERFLOW_SCREENSHOT_DIR)
    await page.screenshot({
      path: path.join(
        process.env.DEERFLOW_SCREENSHOT_DIR,
        `cad-preview-${page.url().includes("/artifacts/view") ? "reader" : "panel"}-${page.viewportSize()!.width}-${name}.png`,
      ),
    });
  // The viewer fits its panel and nothing inside it scrolls sideways.
  const fits = await host.evaluate((element) => {
    const right = element.getBoundingClientRect().right;
    const inside = [...element.shadowRoot!.querySelectorAll("*")].every(
      (node) => node.getBoundingClientRect().right <= right + 0.5,
    );
    const shell = element.shadowRoot!.querySelector(".cad")!;
    return (
      inside &&
      right <= document.documentElement.clientWidth + 0.5 &&
      shell.scrollWidth <= shell.clientWidth
    );
  });
  expect(fits).toBe(true);
  // The page as a whole too. At phone width the chat header's toolbar
  // (chat-instance.tsx, a row that does not shrink) runs past the viewport
  // behind the panel's sheet, with or without this extension, so only the
  // viewer is held to it there.
  if (page.viewportSize()!.width >= 600)
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
}

for (const width of [1440, 390]) {
  test(`GLB, STL and a failed GLB rotate in the panel at ${width} px`, async ({
    page,
  }) => {
    await setup(page, width);
    await openInPanel(page, models[0]!);
    await expectModel(page, models[0]!);
    for (const name of models.slice(1)) {
      await switchTo(page, name);
      await expectModel(page, name);
    }
  });

  test(`the standalone reader shows the same models at ${width} px`, async ({
    page,
  }) => {
    await setup(page, width);
    for (const name of models) {
      await page.goto(readerURL(name));
      await expectModel(page, name);
    }
  });
}

test("view controls, the original download and the edge toggle", async ({
  page,
}) => {
  await setup(page, 1440);
  const panel = await openInPanel(page, models[0]!);
  const host = preview(page, models[0]!);
  await expect(host.locator("canvas")).toBeVisible({ timeout: 20_000 });
  for (const label of [
    "Top view",
    "Front view",
    "Iso view",
    "Fit the model to the view",
    "Reset the camera",
  ])
    await host.getByRole("button", { name: label, exact: true }).click();
  const edges = host.getByRole("button", { name: "Show feature edges" });
  await expect(edges).toHaveAttribute("aria-pressed", "true");
  await edges.click();
  await expect(edges).toHaveAttribute("aria-pressed", "false");
  // A lost context says so and comes back on request, with one live context.
  await host.locator("canvas").evaluate((canvas: HTMLCanvasElement) => {
    const gl = canvas.getContext("webgl2");
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  });
  await expect(host.getByRole("alert")).toContainText("Display lost");
  await host.getByRole("button", { name: "Reload", exact: true }).click();
  await expect(host.getByRole("alert")).toHaveCount(0);
  await expect(host.locator("canvas")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as unknown as { cadProbe: Probe }).cadProbe.live,
      ),
    )
    .toBe(1);
  const download = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: `Download ${models[0]}`, exact: true })
    .click();
  const saved = await (await download).path();
  expect(
    Buffer.compare(
      await readFile(saved),
      await readFile(path.join(cadFixtures, models[0]!)),
    ),
  ).toBe(0);
});

test("a file over 25 MiB and an amplifying GLB fall back to a download with their reason", async ({
  page,
}) => {
  await setup(page, 1440);
  const panel = await openInPanel(page, "huge.glb");
  await expect(
    panel.getByText("larger than the 25 MiB preview limit"),
  ).toBeVisible({ timeout: 20_000 });
  // The panel header's download and the fallback's own.
  await expect(
    panel.getByRole("button", { name: "Download huge.glb", exact: true }),
  ).toHaveCount(2);
  await expect(
    panel.getByRole("button", { name: "Retry preview" }),
  ).toHaveCount(0);
  await switchTo(page, "amplifying.glb");
  const host = preview(page, "amplifying.glb");
  await expect(host.getByRole("status")).toHaveText(
    "This model has more than 1,000,000 triangles, over the preview limit.",
    { timeout: 20_000 },
  );
  await expect(host.locator("canvas")).toHaveCount(0);
  const download = page.waitForEvent("download");
  await host.getByRole("link", { name: "Download original" }).click();
  const saved = await (await download).path();
  expect(Buffer.compare(await readFile(saved), amplifying)).toBe(0);
  expect(
    await page.evaluate(
      () => (window as unknown as { cadProbe: Probe }).cadProbe.created,
    ),
  ).toBe(0);
});

test("twenty file switches leave one live context, idle frames stop and the theme recolours in place", async ({
  page,
}) => {
  const warnings: string[] = [];
  page.on("console", (message) => {
    if (/too many active webgl contexts/i.test(message.text()))
      warnings.push(message.text());
  });
  await setup(page, 1440);
  await openInPanel(page, models[0]!);
  await expect(preview(page, models[0]!).locator("canvas")).toBeVisible({
    timeout: 20_000,
  });
  const probe = () =>
    page.evaluate(() => ({
      ...(window as unknown as { cadProbe: Probe }).cadProbe,
    }));
  for (let i = 1; i <= 20; i++) {
    const name = models[i % models.length]!;
    await switchTo(page, name);
    await expect(preview(page, name).locator("canvas")).toBeVisible({
      timeout: 20_000,
    });
    await expect.poll(async () => (await probe()).live).toBeLessThanOrEqual(1);
  }
  expect((await probe()).created).toBeGreaterThanOrEqual(21);
  expect(warnings).toEqual([]);

  const name = models[20 % models.length]!;
  const host = preview(page, name);
  await page.waitForTimeout(300);
  const before = (await probe()).frames;
  await page.waitForTimeout(1000);
  expect((await probe()).frames - before).toBe(0);

  const shell = host.locator(".cad");
  const light = await shell.getAttribute("data-edge-color");
  await host.locator("canvas").evaluate((canvas) => {
    (canvas as HTMLCanvasElement & { marker?: boolean }).marker = true;
  });
  const created = (await probe()).created;
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await expect(shell).not.toHaveAttribute("data-edge-color", light!);
  expect(
    await host
      .locator("canvas")
      .evaluate(
        (canvas) => (canvas as HTMLCanvasElement & { marker?: boolean }).marker,
      ),
  ).toBe(true);
  expect((await probe()).created).toBe(created);
});

for (const plugins of ["none", "disabled"] as const) {
  test(`with ${plugins === "none" ? "no plugins" : "the extension disabled"}, GLB and STL keep the download fallback`, async ({
    page,
  }) => {
    await setup(page, 1440, plugins);
    const panel = await openInPanel(page, models[0]!);
    for (const name of models.slice(0, 2)) {
      if (name !== models[0]) await switchTo(page, name);
      await expect(
        panel.getByText(
          "Preview is unavailable for this format. Download the original file to view it.",
        ),
      ).toBeVisible();
      await expect(panel.locator("canvas")).toHaveCount(0);
    }
  });
}

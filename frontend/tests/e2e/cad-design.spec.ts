import { expect, test, type Page } from "@playwright/test";

import {
  DesignBackend,
  gatewayRequests,
  mockCadDesign,
  TEXT_ANSWER,
  type Render,
} from "./utils/cad-design";
import { mockLangGraphAPI } from "./utils/mock-api";

// No GPU in CI: WebGL runs on SwiftShader, which Chromium only offers with
// this flag. A local Chromium of another revision comes from the environment.
test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: [
      "--enable-unsafe-swiftshader",
      "--use-angle=swiftshader",
      // A non-localhost name for the test server: a plain-http page there is
      // not a secure context, like http://100.x:2026 over a tailnet.
      "--host-resolver-rules=MAP insecure.test 127.0.0.1",
    ],
  },
});

// The real OpenSCAD wasm loads, compiles and renders in each test.
test.describe.configure({ timeout: 120_000 });

const pageURL = "/workspace/extensions/cad-design/designs";
const CUBE = "width = 20; // [10:1:60]\ncube([width, 20, 20]);\n";
const rendered: Render = {
  ok: true,
  partial: false,
  bbox_mm: [20, 20, 20],
  volume_mm3: 8000,
  manifold: true,
  triangles: 12,
};

async function setup(
  page: Page,
  width: number,
  { webgl = true }: { webgl?: boolean } = {},
) {
  await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
  await page.addInitScript((webgl) => {
    localStorage.setItem("theme", "light");
    if (webgl) return;
    const getContext = Reflect.get(
      HTMLCanvasElement.prototype,
      "getContext",
    ) as (this: HTMLCanvasElement, ...args: unknown[]) => unknown;
    Reflect.set(
      HTMLCanvasElement.prototype,
      "getContext",
      function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
        return type.startsWith("webgl") || type === "experimental-webgl"
          ? null
          : getContext.call(this, type, ...rest);
      },
    );
  }, webgl);
  mockLangGraphAPI(page, { threads: [] });
  const backend = new DesignBackend();
  await mockCadDesign(page, backend);
  return backend;
}

const reported = (backend: DesignBackend) =>
  backend
    .calledWith("report_render")
    .map(({ payload }) => payload.render as Render);

function expectCube(render: Render | undefined, size: number[]) {
  expect(render?.ok).toBe(true);
  expect(render?.manifold).toBe(true);
  expect(render?.triangles).toBe(12);
  render!.bbox_mm!.forEach((value, axis) =>
    expect(Math.abs(value - size[axis]!)).toBeLessThan(1e-3),
  );
}

test("a prompt streams a draft that the browser renders, and a slider redraws without the Gateway", async ({
  page,
}) => {
  const backend = await setup(page, 1440);
  backend.draft = CUBE;
  await page.goto(pageURL);

  // The full layout: no host heading or max-width column; the surface fills
  // the area under the breadcrumb.
  const surface = page.locator('section[aria-label="Designs"]');
  await expect(page.getByRole("button", { name: "New design" })).toBeVisible();
  await expect(page.locator("main .max-w-6xl")).toHaveCount(0);
  const box = (await surface.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(900 - 56 - 2);
  await expect(
    page.getByRole("link", { name: "Designs", exact: true }),
  ).toHaveAttribute("href", pageURL);

  await page.getByRole("button", { name: "New design" }).click();
  await expect(
    page.getByText("Untitled design", { exact: true }),
  ).toBeVisible();
  expect(backend.calledWith("create_design")).toHaveLength(1);

  const prompt = page.getByRole("textbox", { name: /Describe the part/ });
  await prompt.fill("A 20 mm cube with a width parameter");
  await page.getByRole("button", { name: "Send", exact: true }).click();

  // The mocked stream's scad_draft call renders in the real OpenSCAD Worker.
  await expect(page.getByText("20 × 20 × 20 mm", { exact: true })).toBeVisible({
    timeout: 60_000,
  });
  await expect.poll(() => reported(backend).length).toBe(1);
  expectCube(reported(backend)[0], [20, 20, 20]);
  const [version] = backend.versions;
  expect(backend.calledWith("report_render")[0]!.payload.version_id).toBe(
    version!.id,
  );
  expect(backend.calledWith("prompt")[0]!.payload).toMatchObject({
    text: "A 20 mm cube with a width parameter",
  });
  await expect(page.getByText("Here is a first draft.")).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();

  // The run settled: the composer is back and the version is listed.
  await expect(prompt).toBeEnabled();
  // The draft came from the joined stream, not from the reload that settles
  // the run: the page reported it before it reloaded the design.
  const order = backend.calls.map(({ action }) => action);
  expect(order.indexOf("report_render")).toBeGreaterThan(
    order.indexOf("prompt"),
  );
  expect(order.indexOf("report_render")).toBeLessThan(
    order.lastIndexOf("get_design"),
  );
  await page.getByRole("tab", { name: "Versions" }).click();
  await expect(
    page.getByRole("button", { name: /v1.*rendered/ }),
  ).toBeVisible();

  // Dragging a slider renders locally: no request reaches the Gateway.
  await page.getByRole("tab", { name: "Parameters" }).click();
  const slider = page.getByRole("slider", { name: "width" });
  await expect(slider).toBeEnabled();
  const requests = gatewayRequests(page.context());
  await slider.evaluate((input: HTMLInputElement) => {
    input.value = "40";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.getByRole("tab", { name: "Preview" }).click();
  await expect(page.getByText("40 × 20 × 20 mm", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  expect(requests).toEqual([]);

  // Releasing it saves one slider version, which is rendered and reported.
  await page.getByRole("tab", { name: "Parameters" }).click();
  await slider.dispatchEvent("change");
  await expect.poll(() => backend.calledWith("save_version").length).toBe(1);
  expect(backend.calledWith("save_version")[0]!.payload).toMatchObject({
    source: "slider",
    parent_id: version!.id,
    scad: CUBE.replace("width = 20;", "width = 40;"),
  });
  await expect.poll(() => reported(backend).length).toBe(2);
  expectCube(reported(backend)[1], [40, 20, 20]);
});

test("a turn that saves no draft says so instead of showing nothing", async ({
  page,
}) => {
  const backend = await setup(page, 1440);
  backend.draft = null;
  await page.goto(pageURL);
  await page.getByRole("button", { name: "New design" }).click();

  const prompt = page.getByRole("textbox", { name: /Describe the part/ });
  await prompt.fill("A 30 x 20 x 10 mm block with a cone on top");
  await page.getByRole("button", { name: "Send", exact: true }).click();

  await expect(page.getByText(TEXT_ANSWER)).toBeVisible();
  await expect(
    page.getByText(
      "The model answered without saving a draft, so the preview did not change. Ask it to draft the part.",
    ),
  ).toBeVisible();
  await expect(prompt).toBeEnabled();
  await expect(page.getByText("No render yet.")).toBeVisible();
  expect(backend.versions).toHaveLength(0);
  expect(backend.calledWith("report_render")).toHaveLength(0);

  // The next prompt clears it.
  backend.draft = CUBE;
  await prompt.fill("Draft it, please");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("20 × 20 × 20 mm", { exact: true })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText(/without saving a draft/)).toHaveCount(0);
});

test("a syntax error in a hand edit names its line", async ({ page }) => {
  const backend = await setup(page, 1440);
  backend.seed("Bracket", CUBE, rendered);
  await page.goto(pageURL);
  await page.getByRole("button", { name: /Bracket/ }).click();
  await expect(page.getByText("20 × 20 × 20 mm", { exact: true })).toBeVisible({
    timeout: 60_000,
  });

  await page.getByRole("tab", { name: "Code" }).click();
  const editor = page.getByRole("textbox", { name: "Code", exact: true });
  await editor.click();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.insertText("width = 20;\ncube([width, 20, 20];\n");
  await expect(page.getByRole("button", { name: "line 2" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText(/syntax error/i)).toBeVisible();
  // A failed hand edit is not stored until it is saved.
  expect(backend.calledWith("save_version")).toHaveLength(0);
});

test("at 390 px the page switches between Prompt, Preview and Code tabs", async ({
  page,
}) => {
  const backend = await setup(page, 390);
  backend.seed("Phone part", CUBE, rendered);
  await page.goto(pageURL);
  await page.getByRole("button", { name: /Phone part/ }).click();
  await expect(page.getByText("20 × 20 × 20 mm", { exact: true })).toBeVisible({
    timeout: 60_000,
  });

  const tab = (name: string) => page.getByRole("tab", { name, exact: true });
  await expect(tab("Prompt")).toBeVisible();
  // The wide layout's tabs are hidden; parameters live inside Code.
  await expect(tab("Parameters")).toBeHidden();
  await expect(tab("Versions")).toBeHidden();
  await expect(tab("Preview")).toHaveAttribute("aria-selected", "true");
  const prompt = page.getByRole("textbox", { name: /Describe the part/ });
  await expect(prompt).toBeHidden();

  await tab("Code").click();
  await expect(page.getByRole("textbox", { name: "Code" })).toBeVisible();
  await expect(page.getByRole("slider", { name: "width" })).toBeVisible();
  await expect(page.locator("canvas")).toBeHidden();

  await tab("Prompt").click();
  await expect(prompt).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Code" })).toBeHidden();

  await tab("Preview").click();
  await expect(page.locator("canvas")).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});

test("without WebGL the preview says so and the render is still reported", async ({
  page,
}) => {
  const backend = await setup(page, 1440, { webgl: false });
  backend.seed("No GPU", CUBE);
  await page.goto(pageURL);
  await page.getByRole("button", { name: /No GPU/ }).click();
  await expect(page.getByText("20 × 20 × 20 mm", { exact: true })).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByText("This browser could not start the 3D preview."),
  ).toBeVisible();
  await expect.poll(() => reported(backend).length).toBe(1);
  expectCube(reported(backend)[0], [20, 20, 20]);
  await expect(page.locator("canvas")).toHaveCount(0);
});

test("over plain http on a LAN or tailnet name, without crypto.subtle, a draft still renders", async ({
  page,
}, testInfo) => {
  // Browsers expose crypto.subtle only in secure contexts; the wasm check used
  // to require it, so every render failed at http://100.x:2026.
  const backend = await setup(page, 1440);
  backend.seed("Tailnet", CUBE);
  const insecure = new URL(
    pageURL,
    testInfo.project.use.baseURL ?? "http://localhost:3000",
  );
  insecure.hostname = "insecure.test";
  await page.goto(insecure.href);
  expect(
    await page.evaluate(() => ({
      secure: window.isSecureContext,
      subtle: Boolean(globalThis.crypto?.subtle),
    })),
  ).toEqual({ secure: false, subtle: false });
  await page.getByRole("button", { name: /Tailnet/ }).click();
  await expect(page.getByText("20 × 20 × 20 mm", { exact: true })).toBeVisible({
    timeout: 60_000,
  });
  await expect.poll(() => reported(backend).length).toBe(1);
  expectCube(reported(backend)[0], [20, 20, 20]);
});

import { expect, test, type Page } from "@playwright/test";

import {
  DesignBackend,
  FOLDER,
  mockCadDesign,
  RENDER_COMMAND,
  TEXT_ANSWER,
} from "./utils/cad-design";
import { mockLangGraphAPI } from "./utils/mock-api";

// No GPU in CI: WebGL runs on SwiftShader, which Chromium only offers with
// this flag. A local Chromium of another revision comes from the environment.
test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"],
  },
});

const pageURL = "/workspace/extensions/cad-design/designs";

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

const prompt = (page: Page) =>
  page.getByRole("textbox", { name: /Describe the part/ });
const send = (page: Page) =>
  page.getByRole("button", { name: "Send", exact: true }).click();
const tab = (page: Page, name: string) =>
  page.getByRole("tab", { name, exact: true });

test("a prompt streams the run and the preview shows the new version's bodies, views, checks, code and files", async ({
  page,
}) => {
  const backend = await setup(page, 1440);
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
  await expect(page.getByText("make sandbox-cad-image")).toHaveCount(0);

  await page.getByRole("button", { name: "New design" }).click();
  await expect(
    page.getByText("Untitled design", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/^No version yet/)).toBeVisible();

  await prompt(page).fill("A 60 x 40 mm plate with a peg");
  await send(page);

  // The stream's bash call and its result: the folder is listed again and
  // the new version's bodies come from report.json and their STL files.
  await expect(page.getByRole("combobox", { name: "Version" })).toHaveValue(
    "1",
  );
  const bodies = page.getByRole("list", { name: "Bodies" });
  await expect(bodies.getByText("plate", { exact: true })).toBeVisible();
  await expect(bodies.getByText("peg", { exact: true })).toBeVisible();
  await expect(bodies.getByText(/^60 × 40 × 6 mm/)).toBeVisible();
  await expect(bodies.getByText(/^10 × 10 × 21 mm/)).toBeVisible();
  await expect(
    page.getByText("v1 · 2 bodies · rendered in 2.5 s"),
  ).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
  expect(backend.calledWith("prompt")[0]!.payload).toMatchObject({
    text: "A 60 x 40 mm plate with a peg",
    mode: "flash",
  });
  expect(backend.calledWith("prompt")[0]!.payload.viewing).toBeUndefined();
  await expect.poll(() => backend.fileRequests).toContain(`list ${FOLDER}`);
  await expect
    .poll(() => backend.fileRequests)
    .toContain(`read ${FOLDER}/v1/plate.stl`);
  await expect
    .poll(() => backend.fileRequests)
    .toContain(`read ${FOLDER}/v1/peg.stl`);
  // Both STLs parsed in the Worker and drawn: the loading note is gone and no
  // body says it could not be shown.
  await expect(page.getByText("Loading v1…")).toHaveCount(0);
  await expect(bodies.getByText("could not be shown")).toHaveCount(0);

  // The run settled: the composer is back and the history shows the call.
  await expect(prompt(page)).toBeEnabled();
  await expect(page.getByText("v1 is ready.")).toBeVisible();
  await expect(page.getByText(`bash: ${RENDER_COMMAND}`)).toBeVisible();

  // A body can be hidden.
  const peg = page.getByRole("checkbox", { name: "Show peg" });
  await peg.uncheck();
  await expect(peg).not.toBeChecked();

  await tab(page, "Views").click();
  const shaded = page.getByRole("img", { name: "Rendered view shaded.png" });
  await expect(shaded).toBeVisible();
  expect(await shaded.getAttribute("src")).toContain(
    "/artifacts/mnt/user-data/outputs/design/v1/views/shaded.png",
  );
  await expect(
    page.getByRole("img", { name: "Rendered view sections.png" }),
  ).toBeVisible();

  await tab(page, "Checks").click();
  await expect(page.getByText("Rendered in 2.5 s.")).toBeVisible();
  await expect(
    page.getByText("peg: WARNING: Ignoring unknown variable 'wal'"),
  ).toBeVisible();
  await expect(
    page.getByText("13 states checked, 1 overlap, clearance 0.3 mm."),
  ).toBeVisible();
  await expect(
    page.getByText("swing [peg=30]: peg / plate 1.25 mm³"),
  ).toBeVisible();
  await expect(
    page.getByText("peg: bridge spans 14 mm (> 10) at x 0..14"),
  ).toBeVisible();
  await expect(page.getByText(/^Slicer: 21\.3 g, 1h 2m/)).toBeVisible();

  await tab(page, "Code").click();
  await expect(page.getByLabel("Code", { exact: true })).toContainText(
    'BODIES = ["plate", "peg"];',
  );

  await tab(page, "Files").click();
  const gcode = page.getByRole("link", { name: "Download print/print.gcode" });
  await expect(gcode).toHaveAttribute(
    "href",
    /\/api\/threads\/thread-[0-9a-f]+\/artifacts\/mnt\/user-data\/outputs\/design\/v1\/print\/print\.gcode\?download=true$/,
  );
  await expect(
    page.getByRole("link", { name: "Download report.json" }),
  ).toBeVisible();
});

test("a turn that makes no version says so, and the next one shows it", async ({
  page,
}) => {
  const backend = await setup(page, 1440);
  backend.render = false;
  await page.goto(pageURL);
  await page.getByRole("button", { name: "New design" }).click();

  await prompt(page).fill("A plate with two holes");
  await send(page);
  await expect(page.getByText(TEXT_ANSWER)).toBeVisible();
  await expect(
    page.getByText(
      "The model answered without making a new version, so the preview did not change.",
    ),
  ).toBeVisible();
  await expect(prompt(page)).toBeEnabled();
  await expect(page.getByText(/^No version yet/)).toBeVisible();

  backend.render = true;
  await prompt(page).fill("M4, please");
  await send(page);
  await expect(
    page.getByText("v1 · 2 bodies · rendered in 2.5 s"),
  ).toBeVisible();
  await expect(page.getByText(/without making a new version/)).toHaveCount(0);
});

test("a prompt sent while an older version is shown names it, and the answer is shown", async ({
  page,
}) => {
  const backend = await setup(page, 1440);
  await backend.seed("Bracket", 2);
  await page.goto(pageURL);
  await page.getByRole("button", { name: /Bracket/ }).click();

  const version = page.getByRole("combobox", { name: "Version" });
  await expect(version).toHaveValue("2");
  await expect(page.getByText(/^10 × 10 × 22 mm/)).toBeVisible();
  await version.selectOption("1");
  await expect(page.getByText(/^10 × 10 × 21 mm/)).toBeVisible();
  await expect(
    page.getByText(
      "You are looking at v1; your next message tells the model so.",
    ),
  ).toBeVisible();

  await prompt(page).fill("Make this one taller");
  await send(page);
  await expect.poll(() => backend.calledWith("prompt").length).toBe(1);
  expect(backend.calledWith("prompt")[0]!.payload).toMatchObject({
    viewing: 1,
    newest: 2,
  });
  // The run's new version is the answer: it is shown, not the one picked.
  await expect(version).toHaveValue("3");
  await expect(page.getByText(/^10 × 10 × 23 mm/)).toBeVisible();
  await expect(page.getByText(/You are looking at v/)).toHaveCount(0);
});

test("at 390 px the page switches between the Prompt and Preview tabs", async ({
  page,
}) => {
  const backend = await setup(page, 390);
  await backend.seed("Phone part");
  await page.goto(pageURL);
  await page.getByRole("button", { name: /Phone part/ }).click();

  await expect(tab(page, "Prompt")).toBeVisible();
  await expect(tab(page, "Preview").first()).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.locator("canvas")).toBeVisible();
  await expect(prompt(page)).toBeHidden();
  await expect(page.getByText("plate", { exact: true })).toBeVisible();

  await tab(page, "Prompt").click();
  await expect(prompt(page)).toBeVisible();
  await expect(page.locator("canvas")).toBeHidden();

  await tab(page, "Preview").first().click();
  await expect(page.locator("canvas")).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});

test("without WebGL the preview says so and the bodies and checks still show", async ({
  page,
}) => {
  const backend = await setup(page, 1440, { webgl: false });
  await backend.seed("No GPU");
  await page.goto(pageURL);
  await page.getByRole("button", { name: /No GPU/ }).click();
  await expect(
    page.getByText("This browser could not start the 3D preview."),
  ).toBeVisible();
  await expect(page.getByText(/^60 × 40 × 6 mm/)).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);
  await tab(page, "Checks").click();
  await expect(page.getByText("Rendered in 2.5 s.")).toBeVisible();
});

test("without the CAD container the list and the design show the setup commands", async ({
  page,
}) => {
  const backend = await setup(page, 1440);
  backend.container = false;
  await backend.seed("Waiting");
  await page.goto(pageURL);
  await expect(
    page.getByText("The Designs page needs the CAD container."),
  ).toBeVisible();
  await expect(
    page.getByText("make sandbox-enable MODE=container IMAGE=cad"),
  ).toBeVisible();
  await page.getByRole("button", { name: /Waiting/ }).click();
  await expect(
    page.getByText("The Designs page needs the CAD container."),
  ).toBeVisible();
  await expect(page.getByText("then restart the Gateway.")).toBeVisible();
});

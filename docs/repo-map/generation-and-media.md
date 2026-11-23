# Generation, media and documents

```mermaid
flowchart LR
  subgraph img [Local image and video generation]
    imgPage["/workspace/image/new"]
    comfyTools["comfyui tools"]
  end
  subgraph grok [Grok Imagine and voice]
    xaiTools["xai tools"]
    readAloud["read-aloud-button.tsx"]
  end
  subgraph voice [Voice input]
    mic["composer microphone"]
    voiceApi["/api/voice"]
  end
  subgraph cad [CAD parts from a chat]
    cadExt["deerflow-extension-cad"]
    cadEval["make cad-eval"]
  end
  subgraph design [CAD design page]
    designPage["/workspace/extensions/cad-design/designs"]
    scadWorker["OpenSCAD Worker (browser)"]
  end
  subgraph bigdoc [Big documents on small models]
    analyze["analyze_document tool"]
    driftEval["make drift-eval"]
  end
  subgraph media [Media generation skills]
    mediaSkills["skills/public/*-generation"]
  end
  subsSettings[["subscription-settings.tsx"]]
  internetPy[["tools/internet_access.py"]]
  contextBudget[["utils/context_budget.py"]]
  sandbox[["sandbox tools"]]
  comfy{{"ComfyUI (loopback :8188)"}}
  xai{{"xAI Grok API"}}
  whisper{{"Whisper-compatible STT server"}}
  llm{{"LLM providers (vision OCR)"}}
  outputs[("thread outputs directory")]
  comfyTools --> comfy
  xaiTools --> xai
  readAloud --> voiceApi
  voiceApi --> whisper
  voiceApi --> xai
  grok --> subsSettings
  cad --> internetPy
  grok --> internetPy
  analyze --> contextBudget
  analyze --> llm
  img --> outputs
  cad --> outputs
  design --> cad
  design --> outputs
  media --> sandbox
  media --> outputs
```

### Local image and video generation
What: image and short video generation on a local ComfyUI that is provisioned and stocked at startup, with a GPU residency arbiter shared with Ollama and a judged refine loop.
Entry points: /workspace/image/new, workspace header Image button, ComfyUI generation tools, make comfy-*
Files: backend/packages/harness/deerflow/community/comfyui/**, backend/packages/harness/deerflow/config/media_config.py, scripts/comfyui.sh, scripts/comfyui_models.py, scripts/detect_comfyui.py, docker/docker-compose.comfyui.yml, frontend/src/app/workspace/image/new/page.tsx, frontend/src/components/workspace/image-generation-setup.tsx, frontend/src/components/workspace/chats/use-image-launch.ts, frontend/src/core/threads/image-generation.ts
Data: thread outputs directory, ComfyUI model folder
External: ComfyUI on loopback port 8188
Tests: backend/tests/test_comfyui_tools.py, backend/tests/test_comfyui_models.py, backend/tests/test_comfyui_video.py, backend/tests/test_gpu_arbiter.py, backend/tests/test_refine_session.py, backend/tests/test_detect_comfyui.py, frontend/tests/unit/components/workspace/image-generation-setup.dom.test.tsx, frontend/tests/unit/core/threads/image-generation.test.ts

### Grok Imagine and voice
What: on a connected Grok plan an administrator can switch on Grok Imagine image and video generation, X search and Grok voice (read answers aloud, transcribe speech).
Entry points: Settings: Models: Grok features, read-aloud button, xAI tools
Files: backend/packages/harness/deerflow/community/xai/**, backend/app/gateway/routers/voice.py, frontend/src/components/workspace/read-aloud-button.tsx, frontend/src/components/workspace/settings/subscription-settings.tsx
Data: Grok subscription credentials, thread outputs directory
External: xAI Grok API
Tests: backend/tests/test_grok_features.py, backend/tests/test_grok_xai_tools.py, frontend/tests/unit/core/voice-input/read-aloud.test.ts

### Voice input
What: dictation that tries Chrome's on-device recognition, then a Whisper-compatible service on your machine; the vendor cloud is opt-in.
Entry points: composer microphone, POST /api/voice/transcribe
Files: frontend/src/core/voice-input/**, backend/app/gateway/routers/voice.py, backend/packages/harness/deerflow/community/speech/**, backend/packages/harness/deerflow/config/voice_config.py
Data: none
External: browser speech recognition, a local Whisper-compatible STT server
Tests: backend/tests/test_voice_stt.py, frontend/tests/unit/core/voice-input/voice-tiers.test.ts, frontend/tests/unit/core/voice-input/recorder.test.ts, frontend/tests/unit/core/voice-input/speech-recognition.test.ts

### CAD parts from a chat
What: describe a part and get an editable CAD script, a picture of it and STEP, STL, 3MF and GLB files, built by the bundled CAD extension without running the model's code; holes are checked where they are, several bodies print in place or laid out apart, a print block reports how it prints (never pass or fail), and make cad-eval grades a model's delivered parts against ground truth. The files rotate in the panel through the CAD model preview (sidebar-and-workspace.md).
Entry points: cad_build (CAD extension tool), cad-modeling skill, make cad-eval
Files: backend/extensions/sources/deerflow-extension-cad/**, examples/deerflow-extension-cad/**, skills/public/cad-modeling/**, backend/scripts/benchmark/cad_eval/**
Data: thread outputs directory, the operator's printer profile (printer: in the CAD record of config.yaml)
External: none for building (works with the internet switch off); make cad-eval drives a configured model through the running Gateway
Tests: backend/tests/test_cad_extension.py, backend/tests/test_bundled_cad_extension.py, backend/tests/test_cad_runtime_deps.py, backend/tests/blocking_io/test_cad_extension.py, backend/tests/test_context_fit_critical.py, backend/tests/test_bench_cad_eval.py, tests/skills/test_cad_modeling.py, examples/deerflow-extension-cad/tests/test_interpreter.py, examples/deerflow-extension-cad/tests/test_worker_process.py, examples/deerflow-extension-cad/tests/test_build.py, examples/deerflow-extension-cad/tests/test_measure.py, examples/deerflow-extension-cad/tests/test_checks.py, examples/deerflow-extension-cad/tests/test_render.py, examples/deerflow-extension-cad/tests/test_printability.py, examples/deerflow-extension-cad/tests/test_eval_specs.py

### CAD design page
What: Designs in the sidebar opens a page where the assistant drafts a part in OpenSCAD and the viewer's browser renders it while the code streams (OpenSCAD compiled to WebAssembly in a Worker; the Gateway never runs it); every render is a version, the code is editable, top-level numbers are sliders, and Finalize ports the draft to CadQuery and builds it with the CAD module's cad_build, checking the size against the draft. The scad_draft tool reaches design runs only. Host hooks it uses: AgentRuns.start stream_mode and delete_thread (extension API 0.2.14), joinRunStream, models, layout full, the box icon and the deerflow_listed hide flag (Extensions and plugins).
Entry points: /workspace/extensions/cad-design/designs, scad_draft (extension tool), /api/extensions/cad-design/designs/{design_id}/files/{name}, make cad-eval CAD_PATH=design, make extension-disable NAME=cad-design
Files: examples/deerflow-extension-cad-design/**, backend/extensions/sources/deerflow-extension-cad-design/**, backend/scripts/benchmark/cad_eval/design_path.py
Data: design store (SQLite at cad-design/designs.sqlite under DEER_FLOW_HOME), the design's hidden thread and its outputs directory
External: none (OpenSCAD, three.js and CodeMirror are bundled; nothing is fetched from a CDN)
Tests: examples/deerflow-extension-cad-design/tests/test_store.py, examples/deerflow-extension-cad-design/tests/test_actions.py, examples/deerflow-extension-cad-design/tests/test_tool.py, examples/deerflow-extension-cad-design/tests/test_middleware.py, examples/deerflow-extension-cad-design/tests/test_router.py, examples/deerflow-extension-cad-design/tests/test_scad.py, examples/deerflow-extension-cad-design/tests/test_install.py, examples/deerflow-extension-cad-design/tests/test_registration.py, examples/deerflow-extension-cad-design/tests/build.test.mjs, examples/deerflow-extension-cad-design/tests/built-worker.test.mjs, examples/deerflow-extension-cad-design/tests/wasm-loader.test.mjs, examples/deerflow-extension-cad-design/tests/scad-client.test.mjs, examples/deerflow-extension-cad-design/tests/run-stream.test.mjs, backend/tests/test_bundled_cad_design_extension.py, backend/tests/test_context_fit_critical.py, backend/tests/test_extension_agent_runs.py, backend/tests/test_bench_cad_eval.py, frontend/tests/e2e/cad-design.spec.ts

### Big documents on small models
What: analyze_document reads a PDF, EPUB, HTML or zipped book in parts sized for the serving model, transcribes scanned PDFs with a vision model, and make drift-eval checks that long-document answers stay on the question.
Entry points: analyze_document tool, make drift-eval
Files: backend/packages/harness/deerflow/documents/**, backend/packages/harness/deerflow/tools/builtins/analyze_document_tool.py, backend/packages/harness/deerflow/utils/context_budget.py, backend/packages/harness/deerflow/config/documents_config.py, backend/scripts/benchmark/drift_eval/**
Data: thread uploads directory
External: LLM providers (vision OCR, judge model for drift-eval)
Tests: backend/tests/test_analyze_document_tool.py, backend/tests/test_document_analysis.py, backend/tests/test_document_chunking.py, backend/tests/test_document_extraction.py, backend/tests/test_document_ocr.py, backend/tests/test_document_formats.py, backend/tests/test_bench_drift_eval.py

### Media generation skills
What: bundled skills that make images, videos, music, podcasts, slide decks, charts and newsletters inside the sandbox.
Entry points: the skills in the composer or by name (/image-generation, /ppt-generation, ...)
Files: skills/public/image-generation/**, skills/public/image-refine/**, skills/public/video-generation/**, skills/public/music-generation/**, skills/public/podcast-generation/**, skills/public/ppt-generation/**, skills/public/chart-visualization/**, skills/public/newsletter-generation/**
Data: thread outputs directory
External: the generation APIs each skill names
Tests: tests/skills/test_image_generation.py, tests/skills/test_video_generation.py, tests/skills/test_music_generation.py, tests/skills/test_podcast_generation.py, tests/skills/test_ppt_transparency.py, tests/skills/test_chart_visualization.py
